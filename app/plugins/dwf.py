from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

import requests

from app.plugins.base import BasePlugin
from app.plugins.helper.helper import html_to_text


class DWFPlugin(BasePlugin):
    plugin_name = "dwf"
    display_name = "DWF"
    enabled = True
    careers_url = "https://apply.dwfgroup.com/careers-home/jobs?page=1"
    description = "DWF Jibe careers API scraper"
    required_config = ["source_url", "api_url", "domain"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "api_url": "https://apply.dwfgroup.com/api/jobs",
        "domain": "dwfgroup.jibeapply.com",
        "page_size": 100,
        "max_pages": 0,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = str(self.plugin_config.get("source_url") or self.careers_url)
        api_url = str(self.plugin_config.get("api_url") or "").strip()
        domain = str(self.plugin_config.get("domain") or "").strip()
        page_size = max(1, min(int(self.plugin_config.get("page_size", 100)), 100))
        max_pages = int(self.plugin_config.get("max_pages", 0))
        timeout = int(self.plugin_config.get("timeout", 60))
        if not api_url or not domain:
            raise ValueError("DWF API configuration is incomplete")

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Referer": source_url,
            }
        )

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 1
        total: int | None = None

        while True:
            if max_pages > 0 and page > max_pages:
                break

            response = session.get(
                api_url,
                params={
                    "page": page,
                    "limit": page_size,
                    "domain": domain,
                    "internal": "false",
                },
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("jobs") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or not rows:
                break

            total = total or self._safe_int(payload.get("count") or payload.get("totalCount"))
            new_on_page = self._append_jobs(rows, jobs, seen, source_url, page)
            if new_on_page == 0:
                break
            if len(rows) < page_size:
                break
            if total is not None and page * page_size >= total:
                break
            page += 1

        if not jobs:
            raise ValueError("DWF API returned no jobs")
        return jobs

    def _append_jobs(
        self,
        rows: list[Any],
        jobs: list[dict[str, Any]],
        seen: set[str],
        source_url: str,
        page: int,
    ) -> int:
        new_on_page = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else row
            if not isinstance(data, dict):
                continue

            reference = self._clean(data.get("req_id") or data.get("slug") or data.get("id"))
            title = self._clean(data.get("title"))
            if not reference or not title or reference in seen:
                continue

            job_url = self._job_url(data, source_url)
            description = self._description(data.get("description"))
            seen.add(reference)
            new_on_page += 1

            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": self._location(data),
                    "practice_area": self._practice_area(data),
                    "pqe_level": self._extract_pqe(title, description),
                    "description": description,
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "dwf_jibe_api",
                        "listing_page": page,
                        "slug": self._clean(data.get("slug")),
                        "apply_url": self._clean(data.get("apply_url")),
                        "location_name": self._clean(data.get("location_name")),
                        "posted_date": self._clean(data.get("posted_date")),
                        "employment_type": self._values(data.get("tags1")),
                        "department": self._values(data.get("tags5")),
                    },
                }
            )
        return new_on_page

    @classmethod
    def _job_url(cls, data: dict[str, Any], source_url: str) -> str | None:
        explicit = cls._clean(
            data.get("job_url")
            or data.get("url")
            or data.get("canonical_url")
            or data.get("external_url")
        )
        if explicit:
            return explicit
        slug = cls._clean(data.get("slug") or data.get("req_id"))
        if slug:
            return urljoin("https://apply.dwfgroup.com/careers-home/jobs/", slug)
        return cls._clean(data.get("apply_url")) or source_url

    @classmethod
    def _location(cls, data: dict[str, Any]) -> str | None:
        city = cls._clean(data.get("city"))
        country = cls._clean(data.get("country"))
        if city and country:
            return f"{city}, {country}"
        return cls._clean(data.get("location_name") or data.get("address"))

    @classmethod
    def _practice_area(cls, data: dict[str, Any]) -> str | None:
        categories = []
        for category in data.get("categories") or []:
            if isinstance(category, dict):
                name = cls._clean(category.get("name"))
            else:
                name = cls._clean(category)
            if name and name not in categories:
                categories.append(name)
        return "; ".join(categories) or None

    @classmethod
    def _values(cls, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        cleaned: list[str] = []
        for value in values:
            text = cls._clean(value)
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned

    @classmethod
    def _description(cls, value: Any) -> str | None:
        text = cls._clean(value)
        if not text:
            return None
        if "<" in text or "&lt;" in text:
            return html_to_text(text)
        return text

    @staticmethod
    def _extract_pqe(title: str, description: str | None) -> str | None:
        text = f"{title} {description or ''}"
        match = re.search(
            r"\b(?:NQ|\d+(?:\s*(?:-|\u2013|to)\s*\d+)?\+?\s*PQE)\b",
            text,
            flags=re.IGNORECASE,
        )
        return " ".join(match.group(0).split()) if match else None

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
