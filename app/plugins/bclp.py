from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

from app.plugins.base import BasePlugin


class BCLPPlugin(BasePlugin):
    plugin_name = "bclp"
    display_name = "BCLP"
    discoverable = True
    enabled = True
    careers_url = "https://www.bclplaw.com/en-US/careers.html?of=31060&rs=9"
    description = "BCLP London careers scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "max_pages": 0,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = str(self.plugin_config.get("source_url") or self.careers_url)
        timeout = int(self.plugin_config.get("timeout", 60))
        max_pages = int(self.plugin_config.get("max_pages", 0))
        page_size = self._page_size(source_url)

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

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 0

        while True:
            if max_pages > 0 and page >= max_pages:
                break

            response = session.get(self._page_url(source_url, page * page_size), timeout=timeout)
            response.raise_for_status()
            response.encoding = "utf-8"
            soup = BeautifulSoup(response.text, "lxml")
            new_on_page = self._append_jobs(soup, jobs, seen, page + 1)

            if new_on_page == 0 or new_on_page < page_size:
                break
            page += 1

        return jobs

    def _append_jobs(
        self,
        soup: BeautifulSoup,
        jobs: list[dict[str, Any]],
        seen: set[str],
        page: int,
    ) -> int:
        new_on_page = 0
        for link in soup.select("a[href*='FilterJobID=']"):
            job_url = str(link.get("href") or "").strip()
            identifiers = self._identifiers(job_url)
            if identifiers is None:
                continue
            reference, reid, job_id = identifiers
            if reference in seen:
                continue

            card = link.find_parent("div", class_=re.compile(r"styles__card--"))
            title = self._title(card, link)
            if not title:
                continue

            seen.add(reference)
            new_on_page += 1
            posted_date, location = self._card_meta(card)
            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": location,
                    "practice_area": None,
                    "pqe_level": None,
                    "description": None,
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "bclp_careers_html",
                        "virecruit_reid": reid,
                        "virecruit_job_id": job_id,
                        "posted_date": posted_date,
                        "listing_page": page,
                    },
                }
            )
        return new_on_page

    @classmethod
    def _title(cls, card: Tag | None, fallback_link: Tag) -> str | None:
        if card is not None:
            heading = card.select_one("p[class*='styles__heading--'] a[href*='FilterJobID=']")
            if heading is not None:
                return cls._clean(heading.get_text(" ", strip=True))
        return cls._clean(fallback_link.get_text(" ", strip=True))

    @classmethod
    def _card_meta(cls, card: Tag | None) -> tuple[str | None, str | None]:
        if card is None:
            return None, None
        element = card.select_one("span[class*='styles__content--']")
        if element is None:
            return None, None

        lines = [
            cleaned
            for line in element.get_text("\n", strip=True).splitlines()
            if (cleaned := cls._clean(line))
        ]
        if not lines:
            return None, None
        posted_date = re.sub(r"^Posted\s+", "", lines[0], flags=re.IGNORECASE).strip() or None
        location = "; ".join(lines[1:]) or None
        return posted_date, location

    @staticmethod
    def _identifiers(job_url: str) -> tuple[str, str, str] | None:
        query = parse_qs(urlparse(job_url).query)
        reid = (query.get("FilterREID") or [None])[0]
        job_id = (query.get("FilterJobID") or [None])[0]
        if not reid or not job_id:
            return None
        return f"{job_id}:{reid}", str(reid), str(job_id)

    @staticmethod
    def _page_size(source_url: str) -> int:
        value = (parse_qs(urlparse(source_url).query).get("rs") or [9])[0]
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 9

    @staticmethod
    def _page_url(source_url: str, offset: int) -> str:
        if offset <= 0:
            return source_url
        parsed = urlparse(source_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["f"] = str(offset)
        return urlunparse(parsed._replace(query=urlencode(query)))

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None
