from __future__ import annotations

from typing import Any

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class LinklatersPlugin(BasePlugin):
    plugin_name = "linklaters"
    display_name = "Linklaters"
    discoverable = True
    enabled = True
    careers_url = "https://www.linklaters.com/careers/search"
    description = "Linklaters Sitecore Search careers scraper"
    required_config = ["search_url"]
    default_config: dict[str, Any] = {
        "search_url": "https://edge-platform.sitecorecloud.io/v1/search?sitecoreContextId=67yAhNZqwUVkswy8bdokmt",
        "query": "",
        "limit": 20,
        "max_pages": 0,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        search_url = str(self.plugin_config.get("search_url") or self.default_config["search_url"])
        query = str(self.plugin_config.get("query") or "")
        limit = int(self.plugin_config.get("limit", 20))
        max_pages = int(self.plugin_config.get("max_pages", 0))
        timeout = int(self.plugin_config.get("timeout", 60))

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
            }
        )

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        offset = 0
        page = 0
        total: int | None = None

        while True:
            if max_pages > 0 and page >= max_pages:
                break
            if total is not None and offset >= total:
                break

            response = session.post(
                search_url,
                json=self._payload(offset=offset, limit=limit, query=query),
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            widget = (data.get("widgets") or [{}])[0]
            total = self._to_int(widget.get("total_item")) or total
            items = widget.get("content") or []
            if not items:
                break

            new_jobs = 0
            for item in items:
                reference = self._clean(item.get("id"))
                job_url = self._clean(item.get("jobapplyurl"))
                title = self._clean(item.get("jobtitle"))
                if not reference or not job_url or not title or reference in seen:
                    continue

                seen.add(reference)
                new_jobs += 1
                jobs.append(
                    {
                        "job_url": job_url,
                        "firm_name": self.firm_name,
                        "title": title,
                        "office_location": self._location(item),
                        "practice_area": self._clean(item.get("jobfamilygroup")),
                        "pqe_level": None,
                        "description": self._html_to_text(item.get("description")),
                        "source_reference": reference,
                        "status": "LIVE",
                        "extra_info": {
                            "source": "linklaters_sitecore_search",
                            "listing_page": page + 1,
                            "job_id": reference,
                            "job_posting_date": self._clean(item.get("jobpostingdate")),
                            "job_type": self._clean(item.get("type")),
                            "source_id": self._clean(item.get("source_id")),
                            "search_query": query,
                        },
                    }
                )

            if new_jobs == 0:
                break
            offset += limit
            page += 1

        return jobs

    @staticmethod
    def _payload(offset: int, limit: int, query: str) -> dict[str, Any]:
        search: dict[str, Any] = {
            "offset": offset,
            "facet": {"all": True, "sort": {"name": "text", "order": "asc"}},
            "sort": {"choices": True},
            "limit": limit,
            "content": {},
        }
        if query:
            search["query"] = {"keyphrase": query, "operator": "and"}

        return {
            "context": {"locale": {"country": "gb", "language": "en"}},
            "widget": {
                "items": [
                    {
                        "entity": "job",
                        "rfk_id": "rfkid_7",
                        "search": search,
                    }
                ]
            },
        }

    @classmethod
    def _location(cls, item: dict[str, Any]) -> str | None:
        primary = cls._clean(item.get("jobprimarylocation"))
        country = cls._clean(item.get("joblocationcountry"))
        if primary and country and country.casefold() not in primary.casefold():
            return f"{primary}, {country}"
        return primary or country

    @staticmethod
    def _html_to_text(html: Any) -> str | None:
        if not html:
            return None
        soup = BeautifulSoup(str(html), "html.parser")
        text = soup.get_text("\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines) or None

    @staticmethod
    def _to_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
