# app/plugins/workday.py

import requests

from datetime import datetime

from app.plugins.base import BasePlugin
from app.schemas.job_result import JobResult


class WorkdayPlugin(BasePlugin):

    def __init__(
        self,
        firm_name: str,
        api_url: str,
        careers_url: str,
        max_pages: int | None = None
    ):
        self.firm_name = firm_name
        self.api_url = api_url
        self.careers_url = careers_url
        self.max_pages = max_pages

    async def scrape(self):

        all_jobs = []

        offset = 0
        limit = 20
        page = 0

        while True:

            if self.max_pages is not 0 and page >= self.max_pages:
                break

            payload = {
                "limit": limit,
                "offset": offset,
                "searchText": ""
            }

            response = requests.post(
                self.api_url,
                json=payload,
                timeout=60
            )

            response.raise_for_status()
            data = response.json()

            jobs = data.get("jobPostings", [])

            if not jobs:
                break

            for job in jobs:

                all_jobs.append(
                    JobResult(
                        job_url=(
                            self.careers_url
                            + job.get("externalPath", "")
                        ),
                        firm_name=self.firm_name,
                        office_location=job.get(
                            "locationsText",
                            ""
                        ),
                        practice_area=None,
                        pqe_level=None,
                        status="live",
                        extra_info={
                            "title": job.get("title"),
                            "job_id": job.get("bulletFields", [])
                        }
                    )
                )

            offset += limit
            page += 1

        return all_jobs