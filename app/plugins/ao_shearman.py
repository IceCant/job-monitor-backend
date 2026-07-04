from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class AOShearmanPlugin(BasePlugin):
    plugin_name = "ao_shearman"
    display_name = "A&O Shearman"
    enabled = True
    careers_url = (
        "https://careers.aoshearman.com/en/search-jobs"
        "?acm=ALL"
        "&alrpm=2635167-6269131-2648110-2643743"
        "&ascf=%5b%7B%22key%22:%22ALL%22,%22value%22:%22%22%7D%5d"
    )
    description = "A&O Shearman Radancy careers scraper"
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

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        total_pages: int | None = None
        page = 1

        while True:
            if max_pages > 0 and page > max_pages:
                break
            if total_pages is not None and page > total_pages:
                break

            page_url = source_url if page == 1 else self._page_url(source_url, page)
            response = session.get(page_url, timeout=timeout)
            response.raise_for_status()
            response.encoding = "utf-8"

            soup = BeautifulSoup(response.text, "html.parser")
            total_pages = total_pages or self._total_pages(soup)
            before = len(jobs)
            self._append_jobs(soup, page_url, page, jobs, seen)
            if len(jobs) == before:
                break
            page += 1

        return jobs

    def _append_jobs(
        self,
        soup: BeautifulSoup,
        page_url: str,
        page: int,
        jobs: list[dict[str, Any]],
        seen: set[str],
    ) -> None:
        for item in soup.select("li.search-results-list__item"):
            link = item.select_one("a.search-results-list__job-link[href]")
            if link is None:
                continue

            href = str(link.get("href") or "").strip()
            title = self._clean(link.get_text(" ", strip=True))
            job_url = urljoin(page_url, href)
            reference = self._reference(link, job_url)
            if not href or not title or not reference or reference in seen:
                continue

            seen.add(reference)
            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": self._text(item, ".job-location"),
                    "practice_area": None,
                    "pqe_level": None,
                    "description": None,
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "aoshearman_radancy_html",
                        "listing_page": page,
                        "brand_name": self._text(item, ".brand-name"),
                    },
                }
            )

    @staticmethod
    def _page_url(source_url: str, page: int) -> str:
        parsed = urlparse(source_url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        query["p"] = [str(page)]
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    @staticmethod
    def _total_pages(soup: BeautifulSoup) -> int:
        container = soup.select_one("[data-selector-name='searchresults']") or soup.select_one("[data-total-pages]")
        value = container.get("data-total-pages") if container else None
        try:
            pages = int(str(value or "1"))
        except ValueError:
            pages = 1
        return max(pages, 1)

    @classmethod
    def _reference(cls, link: Any, job_url: str) -> str | None:
        data_id = cls._clean(link.get("data-job-id"))
        if data_id:
            return data_id

        parts = [part for part in urlparse(job_url).path.split("/") if part]
        for part in reversed(parts):
            if part.isdigit():
                return part

        match = re.search(r"(\d{6,})", job_url)
        return match.group(1) if match else None

    @classmethod
    def _text(cls, root: Any, selector: str) -> str | None:
        element = root.select_one(selector) if root else None
        if element is None:
            return None
        return cls._clean(element.get_text(" ", strip=True))

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None
