from __future__ import annotations

from typing import Any

import requests

from app.plugins.base import BasePlugin


class DechertPlugin(BasePlugin):
    plugin_name = "dechert"
    display_name = "Dechert"
    enabled = True
    careers_url = "https://www.dechert.com/careers.html#position=Experienced+Lawyer"
    description = "Dechert careers JSON scraper"
    required_config = ["api_url"]
    default_config = {
        "source_url": careers_url,
        "api_url": "https://www.dechert.com/bin/careersSearch",
        "position": "Experienced Lawyer",
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        api_url = self.plugin_config.get("api_url") or self.default_config["api_url"]
        timeout = int(self.plugin_config.get("timeout", 60))
        position = str(self.plugin_config.get("position") or "").strip()

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://www.dechert.com/careers.html",
            }
        )

        response = session.get(api_url, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        positions = data.get("OpenPositions") if isinstance(data, dict) else []
        if not isinstance(positions, list):
            return []

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in positions:
            if not isinstance(item, dict):
                continue
            if position and str(item.get("Type") or "").strip() != position:
                continue

            reference = str(item.get("ID") or "").strip()
            title = str(item.get("Title") or "").strip()
            job_url = str(item.get("Url") or "").strip()
            if not reference or not title or not job_url or reference in seen:
                continue
            seen.add(reference)

            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": self._locations(item.get("Locations")),
                    "practice_area": self._clean(item.get("JobFamily")),
                    "pqe_level": None,
                    "description": None,
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "dechert_careers_json",
                        "posted": self._clean(item.get("Posted")),
                        "position_type": self._clean(item.get("Type")),
                    },
                }
            )

        return jobs

    @classmethod
    def _locations(cls, raw_locations: Any) -> str | None:
        if not isinstance(raw_locations, list):
            return None
        locations: list[str] = []
        for item in raw_locations:
            if not isinstance(item, dict):
                continue
            value = cls._clean(item.get("Location"))
            if value and value not in locations:
                locations.append(value)
        return "; ".join(locations) or None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None
