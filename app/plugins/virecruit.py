from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

from app.plugins.base import BasePlugin


class ViRecruitPlugin(BasePlugin):
    """Shared scraper for viRecruit self-apply job boards."""

    plugin_name = "virecruit"
    display_name = "viRecruit"
    discoverable = False
    source_name = "virecruit_html"
    required_config = ["source_url"]
    default_config = {"timeout": 60}

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = self.plugin_config.get("source_url") or self.careers_url
        if not source_url or not self.careers_url:
            raise ValueError("viRecruit plugin requires source_url and careers_url")

        timeout = int(self.plugin_config.get("timeout", 60))
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                )
            }
        )

        response, soup = self._fetch_board(session, str(source_url), timeout)
        expected_host = urlparse(self.careers_url).hostname

        # Saved Tag URLs eventually expire. Retry through the stable filter URL,
        # which viRecruit redirects to the board's current generated tag.
        if urlparse(response.url).hostname != expected_host or not soup.select_one("table.event-list"):
            response, soup = self._fetch_board(session, self.careers_url, timeout)

        if not soup.select_one("table.event-list"):
            raise ValueError(f"{self.display_name} viRecruit job table was not found")

        board_url = response.url
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()

        for row in soup.select("table.event-list tr"):
            title = self._text(row, "h4")
            apply_link = row.select_one("td.rptAction a[aria-label]")
            reference = self._clean(apply_link.get("aria-label")) if apply_link else None
            if not title or not reference or reference in seen:
                continue
            seen.add(reference)

            meta = self._meta(row)
            description = (
                self._element_text(row.select_one("section.description div.description"))
                or self._element_text(row.select_one("section.summary div.summary"))
            )

            jobs.append(
                {
                    "job_url": f"{self.careers_url}#job={reference}",
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": meta.get("Office"),
                    "practice_area": meta.get("Practice Area"),
                    "pqe_level": self.extract_pqe(title, description),
                    "description": description,
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": self.source_name,
                        "apply_url": urljoin(board_url, apply_link.get("href") or ""),
                        "date_posted": meta.get("Date Posted"),
                        "application_deadline": meta.get("Application Deadline"),
                    },
                }
            )

        return jobs

    def extract_pqe(self, title: str, description: str | None) -> str | None:
        return None

    @staticmethod
    def _fetch_board(
        session: requests.Session, source_url: str, timeout: int
    ) -> tuple[requests.Response, BeautifulSoup]:
        response = session.get(source_url, timeout=timeout)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response, BeautifulSoup(response.text, "html.parser")

    @classmethod
    def _meta(cls, row: Tag) -> dict[str, str]:
        meta: dict[str, str] = {}
        for item in row.select("section.sub-title h5"):
            span = item.select_one("span")
            if span is None:
                continue
            value = cls._clean(span.get_text(" ", strip=True))
            span.extract()
            key = cls._clean(item.get_text(" ", strip=True))
            if key and value:
                meta[key] = value
        return meta

    @classmethod
    def _element_text(cls, element: Tag | None) -> str | None:
        if element is None:
            return None
        for child in element.select("script, style"):
            child.decompose()
        lines = [cls._clean(line) for line in element.get_text("\n", strip=True).splitlines()]
        return "\n".join(line for line in lines if line) or None

    @classmethod
    def _text(cls, root: Tag, selector: str) -> str | None:
        element = root.select_one(selector)
        return cls._clean(element.get_text(" ", strip=True)) if element else None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None
