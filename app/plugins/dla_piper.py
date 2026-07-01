from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class DLAPiperPlugin(BasePlugin):
    plugin_name = "dla_piper"
    display_name = "DLA Piper"
    discoverable = True
    enabled = True
    careers_url = "https://careers.dlapiper.com/jobs/index.html?sort=by-default"
    description = "DLA Piper careers JSON scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "loader_url": "https://careers.dlapiper.com/system/modules/com.dlapiper.careers/functions/get-jobs.json",
        "sort": "by-default",
        "query": "",
        "max_pages": 0,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        loader_url = str(self.plugin_config.get("loader_url") or self.default_config["loader_url"])
        timeout = int(self.plugin_config.get("timeout", 60))
        max_pages = int(self.plugin_config.get("max_pages", 0))
        sort = str(self.plugin_config.get("sort") or "by-default")
        query = str(self.plugin_config.get("query") or "")

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                "Content-Type": "application/json",
                "Referer": self.careers_url or "https://careers.dlapiper.com/jobs/index.html",
            }
        )

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 1

        while True:
            if max_pages > 0 and page > max_pages:
                break

            response = session.post(
                loader_url,
                json={"query": query, "page": str(page), "sort": sort},
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("result") != "success":
                raise ValueError(f"DLA Piper loader returned {data.get('result') or 'unknown result'}")

            items = data.get("items") or []
            if not items:
                break

            new_jobs = 0
            for item in items:
                reference = self._clean(item.get("id"))
                title = self._clean(item.get("title"))
                path = self._clean(item.get("url"))
                if not reference or not title or not path or reference in seen:
                    continue

                seen.add(reference)
                new_jobs += 1
                job_url = urljoin("https://careers.dlapiper.com", path)
                office_location = self._clean(item.get("location"))
                if not office_location:
                    office_location = self._fetch_detail_location(session, job_url, timeout)
                jobs.append(
                    {
                        "job_url": job_url,
                        "firm_name": self.firm_name,
                        "title": title,
                        "office_location": office_location,
                        "practice_area": self._clean(item.get("function")),
                        "pqe_level": None,
                        "description": None,
                        "source_reference": reference,
                        "status": "LIVE",
                        "extra_info": {
                            "source": "dla_piper_json",
                            "listing_page": page,
                            "num_found": data.get("numFound"),
                        },
                    }
                )

            if not data.get("hasMore") or new_jobs == 0:
                break
            page += 1

        return jobs

    def _fetch_detail_location(
        self,
        session: requests.Session,
        job_url: str,
        timeout: int,
    ) -> str | None:
        try:
            response = session.get(job_url, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException:
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(" ", strip=True)
        for pattern in [
            r"\bin our ([A-Z][A-Za-z .'-]+?) office\b",
            r"\bin the ([A-Z][A-Za-z .'-]+?) office\b",
        ]:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()

        if "/jobs/nz/" in job_url.casefold():
            return "New Zealand"
        return None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
