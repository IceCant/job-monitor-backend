from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class ClearyGottliebPlugin(BasePlugin):
    plugin_name = "cleary_gottlieb"
    display_name = "Cleary Gottlieb"
    enabled = True
    careers_url = (
        "https://legalrecruit-eu.cgsh.com/EUselfapply/viRecruitSelfApply/"
        "RecDefault.aspx?FilterREID=2&FilterJobCategoryID=1"
    )
    description = "Cleary Gottlieb EU viRecruit self-apply scraper"
    required_config = ["source_url"]
    default_config = {
        "source_url": careers_url,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = self.plugin_config.get("source_url") or self.careers_url
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

        response = session.get(source_url, timeout=timeout)
        response.raise_for_status()

        # Cleary periodically retires viRecruit Tag URLs. Its stable qualified-lawyer
        # filter redirects to the current tag, so recover old saved firm configs here.
        if urlparse(response.url).hostname != "legalrecruit-eu.cgsh.com":
            response = session.get(self.careers_url, timeout=timeout)
            response.raise_for_status()

        response.encoding = "utf-8"
        board_url = response.url

        soup = BeautifulSoup(response.text, "html.parser")
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
                self._html_to_text(str(row.select_one("section.description div.description")))
                or self._html_to_text(str(row.select_one("section.summary div.summary")))
            )

            jobs.append(
                {
                    "job_url": f"{board_url}#job={reference}",
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": meta.get("Office"),
                    "practice_area": meta.get("Practice Area"),
                    "pqe_level": self._pqe_from_title(title),
                    "description": description,
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "cleary_gottlieb_virecruit_html",
                        "apply_url": urljoin(board_url, apply_link.get("href") or "") if apply_link else None,
                        "date_posted": meta.get("Date Posted"),
                        "application_deadline": meta.get("Application Deadline"),
                    },
                }
            )

        return jobs

    @classmethod
    def _meta(cls, row: BeautifulSoup) -> dict[str, str]:
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

    @staticmethod
    def _pqe_from_title(title: str) -> str | None:
        lower = title.lower()
        marker = "pqe"
        if marker not in lower:
            return None
        start = max(0, lower.rfind("(", 0, lower.find(marker)))
        end = lower.find(")", lower.find(marker))
        if start >= 0 and end > start:
            return title[start + 1 : end].strip()
        return None

    @classmethod
    def _html_to_text(cls, html: str | None) -> str | None:
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        for element in soup.select("script, style"):
            element.decompose()
        lines = [
            cls._clean(line)
            for line in soup.get_text("\n", strip=True).splitlines()
        ]
        text = "\n".join(line for line in lines if line)
        return text or None

    @classmethod
    def _text(cls, root: BeautifulSoup, selector: str) -> str | None:
        element = root.select_one(selector)
        return cls._clean(element.get_text(" ", strip=True)) if element else None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None
