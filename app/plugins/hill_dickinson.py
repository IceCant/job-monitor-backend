from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin
from app.plugins.helper.helper import html_to_text


class HillDickinsonPlugin(BasePlugin):
    plugin_name = "hill_dickinson"
    display_name = "Hill Dickinson"
    enabled = True
    careers_url = "https://careers.hilldickinson.com/legal-professionals"
    description = "Hill Dickinson Hireful CMS legal professionals scraper"
    required_config = ["source_url", "api_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "api_url": (
            "https://api.sitehub.io/collection/668e943a0eb1506ba56f37b2/"
            "items?order=columns.location_ASC&limit=9999&offset=0&paginate=false"
        ),
        "legal_professional_field": "Fee Earner",
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = str(self.plugin_config.get("source_url") or self.careers_url)
        api_url = str(self.plugin_config.get("api_url") or "")
        legal_professional_field = str(
            self.plugin_config.get("legal_professional_field") or "Fee Earner"
        )
        timeout = int(self.plugin_config.get("timeout", 60))
        if not api_url:
            raise ValueError("Hill Dickinson API URL is required")

        response = requests.get(
            api_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Origin": "https://careers.hilldickinson.com",
                "Referer": source_url,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("collection") or []
        if not isinstance(items, list):
            raise ValueError("Hill Dickinson API returned an unexpected collection shape")

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            columns = item.get("columns") if isinstance(item, dict) else None
            if not isinstance(columns, dict):
                continue
            if columns.get("web-published") is not True:
                continue
            if self._clean(columns.get("custom-field-s6")) != legal_professional_field:
                continue

            title = self._clean(columns.get("title"))
            slug = self._clean(columns.get("slug")) or self._clean(columns.get("name"))
            job_id = self._clean(columns.get("job-id"))
            reference = f"HD-{job_id}" if job_id else self._clean(item.get("id"))
            if not title or not slug or not reference or reference in seen:
                continue

            seen.add(reference)
            description = html_to_text(self._content_html(columns.get("content")))
            jobs.append(
                {
                    "job_url": urljoin(source_url, f"/job/{slug}"),
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": self._clean(columns.get("location")),
                    "practice_area": self._clean(columns.get("department")),
                    "pqe_level": self._extract_pqe(title, description),
                    "description": description,
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "hill_dickinson_sitehub_api",
                        "api_item_id": self._clean(item.get("id")),
                        "apply_url": self._href(columns.get("apply-url-new")),
                        "closing_date": self._clean(columns.get("closing-date")),
                        "contract_type": self._clean(columns.get("contract-type")),
                        "hours": self._clean(columns.get("hours")),
                        "salary": self._clean(columns.get("salary")),
                        "job_type": self._clean(columns.get("job-type")),
                        "role_type": self._clean(columns.get("role-type")),
                        "updated_at": self._clean(item.get("updatedAt"))
                        or self._clean(columns.get("updatedAt")),
                    },
                }
            )

        if not jobs:
            raise ValueError("Hill Dickinson API returned no legal professional jobs")
        return jobs

    @classmethod
    def _content_html(cls, value: Any) -> str | None:
        if isinstance(value, list):
            chunks = [
                cls._clean(item.get("content"))
                for item in value
                if isinstance(item, dict)
            ]
            return "\n".join(chunk for chunk in chunks if chunk) or None
        return cls._clean(value)

    @classmethod
    def _href(cls, html: Any) -> str | None:
        value = cls._clean(html)
        if not value:
            return None
        soup = BeautifulSoup(value, "lxml")
        link = soup.select_one("a[href]")
        return cls._clean(link.get("href") if link else None)

    @staticmethod
    def _extract_pqe(title: str | None, description: str | None) -> str | None:
        match = re.search(
            r"\b(?:NQ|\d+(?:\s*(?:-|\u2013|to)\s*\d+)?\+?\s*(?:years?\s*)?PQE\+?)\b",
            f"{title or ''} {description or ''}",
            flags=re.IGNORECASE,
        )
        return " ".join(match.group(0).split()) if match else None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None
