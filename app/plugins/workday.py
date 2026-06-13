# app/plugins/workday.py

import requests
from typing import Any

from app.plugins.base import BasePlugin
from app.schemas.job_result import JobResult


def _to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return str(value)


def _to_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


class WorkdayPlugin(BasePlugin):
    plugin_name = "workday"
    display_name = "NRF Workday"
    enabled = True
    careers_url = "https://nrf.wd3.myworkdayjobs.com/External"
    description = "Scraper for Workday-powered careers APIs"
    required_config = ["api_url", "careers_url"]
    default_config = {
        "api_url": "https://nrf.wd3.myworkdayjobs.com/wday/cxs/nrf/External/jobs",
        "max_pages": 0,
    }

    def __init__(
        self,
        firm_name: str,
        plugin_config: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        super().__init__(firm_name=firm_name, plugin_config=plugin_config, **kwargs)
        cfg = self.plugin_config
        # Allow either plugin_config values or direct kwargs for flexibility.
        api_url = _to_optional_str(kwargs.get("api_url") or cfg.get("api_url"))
        careers_url = _to_optional_str(kwargs.get("careers_url") or cfg.get("careers_url"))
        self.max_pages = _to_optional_int(kwargs.get("max_pages", cfg.get("max_pages")))

        if not api_url or not careers_url:
            raise ValueError("Workday plugin requires api_url and careers_url")

        self.api_url: str = api_url
        self.careers_url: str = careers_url

    async def scrape(self):

        all_jobs = []

        offset = 0
        limit = 20
        page = 0

        while True:

            if self.max_pages != 0 and self.max_pages is not None and page >= self.max_pages:
                break

            payload = {
                "limit": limit,
                "offset": offset,
                "searchText": ""
            }

            api_url = str(self.api_url)

            response = requests.post(
                api_url,
                json=payload,
                timeout=60
            )

            response.raise_for_status()
            data = response.json()

            jobs = data.get("jobPostings", [])

            if not jobs:
                break

            for job in jobs:
                bullet_fields = job.get("bulletFields", []) or []
                reference = bullet_fields[0] if bullet_fields else None

                all_jobs.append(
                    JobResult(
                        job_url=(
                            self.careers_url
                            + job.get("externalPath", "")
                        ),
                        firm_name=self.firm_name,
                        title=job.get("title"),
                        office_location=job.get(
                            "locationsText",
                            ""
                        ),
                        practice_area=None,
                        pqe_level=None,
                        description=job.get("description"),
                        source_reference=reference,
                        status="LIVE",
                        extra_info={
                            "title": job.get("title"),
                            "job_id": reference,
                            "bullet_fields": bullet_fields,
                        }
                    )
                )

            offset += limit
            page += 1

        return all_jobs