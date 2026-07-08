from __future__ import annotations

import re
from typing import Any

import requests

from app.plugins.base import BasePlugin
from app.plugins.helper.helper import html_to_text


class BurgesSalmonPlugin(BasePlugin):
    plugin_name = "burges_salmon"
    display_name = "Burges Salmon"
    enabled = True
    careers_url = "https://www.burges-salmon.com/jobs/"
    description = "Burges Salmon public Algolia job index scraper"
    required_config = ["search_url", "application_id", "api_key", "index_name"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "search_url": "https://J4U7WALZ7D-dsn.algolia.net/1/indexes/jobs/query",
        "application_id": "J4U7WALZ7D",
        "api_key": "cc4f30a5af48f421772bb6928b39468c",
        "index_name": "jobs",
        "page_size": 100,
        "max_pages": 0,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        search_url = str(self.plugin_config.get("search_url") or "").strip()
        application_id = str(self.plugin_config.get("application_id") or "").strip()
        api_key = str(self.plugin_config.get("api_key") or "").strip()
        page_size = max(1, min(int(self.plugin_config.get("page_size", 100)), 1000))
        max_pages = int(self.plugin_config.get("max_pages", 0))
        timeout = int(self.plugin_config.get("timeout", 60))
        if not search_url or not application_id or not api_key:
            raise ValueError("Burges Salmon Algolia configuration is incomplete")

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                "Content-Type": "application/json",
                "Referer": self.careers_url,
                "X-Algolia-Application-Id": application_id,
                "X-Algolia-API-Key": api_key,
            }
        )

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 0
        total_pages = 1

        while page < total_pages:
            if max_pages > 0 and page >= max_pages:
                break
            response = session.post(
                search_url,
                json={"query": "", "hitsPerPage": page_size, "page": page},
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            hits = payload.get("hits") or []
            total_pages = max(1, int(payload.get("nbPages") or 1))

            for hit in hits:
                reference = self._clean(hit.get("ID")) or self._clean(hit.get("objectID"))
                title = self._clean(hit.get("post_title"))
                job_url = self._clean(hit.get("guid"))
                if not reference or not title or not job_url or reference in seen:
                    continue

                seen.add(reference)
                locations = self._labels(hit.get("location"))
                departments = self._labels(hit.get("department"))
                terms = self._labels(hit.get("job-term"))
                description = html_to_text(self._clean(hit.get("post_content")))
                jobs.append(
                    {
                        "job_url": job_url,
                        "firm_name": self.firm_name,
                        "title": title,
                        "office_location": "; ".join(locations) or None,
                        "practice_area": "; ".join(departments) or None,
                        "pqe_level": self._extract_pqe(title, description),
                        "description": description,
                        "source_reference": reference,
                        "status": "LIVE",
                        "extra_info": {
                            "source": "burges_salmon_algolia",
                            "listing_page": page + 1,
                            "posted_date": self._clean(hit.get("display_date")),
                            "job_category": self._labels(hit.get("job-category")),
                            "job_term": terms,
                            "algolia_object_id": self._clean(hit.get("objectID")),
                        },
                    }
                )
            page += 1

        if not jobs:
            raise ValueError("Burges Salmon search index returned no jobs")
        return jobs

    @classmethod
    def _labels(cls, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        labels: list[str] = []
        for value in values:
            clean = cls._clean(value)
            if not clean:
                continue
            label = clean.replace("-", " ").title()
            if label not in labels:
                labels.append(label)
        return labels

    @staticmethod
    def _extract_pqe(title: str, description: str | None) -> str | None:
        text = f"{title} {description or ''}"
        match = re.search(
            r"\b(?:NQ|\d+(?:\s*(?:-|–|to)\s*\d+)?\+?\s*PQE)\b",
            text,
            flags=re.IGNORECASE,
        )
        return " ".join(match.group(0).split()) if match else None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None
