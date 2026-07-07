from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests

from app.plugins.base import BasePlugin


class BCLPPlugin(BasePlugin):
    plugin_name = "bclp"
    display_name = "BCLP"
    discoverable = True
    enabled = True
    careers_url = "https://www.bclplaw.com/en-US/careers.html?rs=50"
    description = "BCLP careers search API scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "records_per_page": 50,
        "max_pages": 0,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = str(self.plugin_config.get("source_url") or self.careers_url)
        timeout = int(self.plugin_config.get("timeout", 60))
        max_pages = int(self.plugin_config.get("max_pages", 0))
        page_size = int(self.plugin_config.get("records_per_page", 50))

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                "Accept": "*/*",
                "Referer": source_url,
            }
        )

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 0
        total: int | None = None

        while True:
            if max_pages > 0 and page >= max_pages:
                break

            offset = page * page_size
            response = session.get(self._api_url(source_url, offset, page_size), timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            hits_container = payload.get("hits", {}).get("ALL", {}) if isinstance(payload, dict) else {}
            hits = hits_container.get("hits", []) if isinstance(hits_container, dict) else []
            total = total or self._safe_int(hits_container.get("total"))
            new_on_page = self._append_jobs(hits, jobs, seen, page + 1)

            if new_on_page == 0 or len(hits) < page_size:
                break
            if total is not None and offset + len(hits) >= total:
                break
            page += 1

        return jobs

    def _append_jobs(
        self,
        hits: list[Any],
        jobs: list[dict[str, Any]],
        seen: set[str],
        page: int,
    ) -> int:
        new_on_page = 0
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            job_url = self._clean(hit.get("job_description_url"))
            identifiers = self._identifiers(job_url)
            if not job_url or identifiers is None:
                continue
            reference, reid, job_id = identifiers
            if reference in seen:
                continue

            title = self._clean(hit.get("name"))
            if not title:
                continue

            seen.add(reference)
            new_on_page += 1
            location = self._locations(hit)
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
                        "source": "bclp_search_api",
                        "api_content_id": hit.get("id") or hit.get("_id"),
                        "api_job_id": hit.get("job_id"),
                        "virecruit_reid": reid,
                        "virecruit_job_id": job_id,
                        "posted_date": self._clean(hit.get("date")),
                        "listing_page": page,
                    },
                }
            )
        return new_on_page

    @classmethod
    def _locations(cls, hit: dict[str, Any]) -> str | None:
        offices = hit.get("content_data", {}).get("offices", [])
        if not isinstance(offices, list):
            return None

        locations: list[str] = []
        seen: set[str] = set()
        for office in offices:
            if not isinstance(office, dict):
                continue
            name = cls._clean(office.get("name"))
            if name and name not in seen:
                locations.append(name)
                seen.add(name)
        return "; ".join(locations) or None

    @staticmethod
    def _identifiers(job_url: str | None) -> tuple[str, str, str] | None:
        if not job_url:
            return None
        query = parse_qs(urlparse(job_url).query)
        reid = (query.get("FilterREID") or [None])[0]
        job_id = (query.get("FilterJobID") or [None])[0]
        if not reid or not job_id:
            return None
        return f"{job_id}:{reid}", str(reid), str(job_id)

    @classmethod
    def _api_url(cls, source_url: str, offset: int, page_size: int) -> str:
        parsed = urlparse(source_url)
        if parsed.path == "/_site/search":
            api_parsed = parsed
        else:
            api_parsed = parsed._replace(path="/_site/search", query="")

        query = parse_qs(api_parsed.query, keep_blank_values=True)
        query.update(
            {
                "rs": [str(max(1, page_size))],
                "f": [str(max(0, offset))],
                "space": [str(query.get("space", ["1019805"])[0])],
                "v": [str(query.get("v", ["job_listings"])[0])],
            }
        )
        return urlunparse(api_parsed._replace(query=urlencode(query, doseq=True)))

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None
