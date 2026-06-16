import json
import re
from typing import Any
from urllib.parse import urlencode

import requests

from app.plugins.base import BasePlugin


class HsfKramerPlugin(BasePlugin):
    plugin_name = "hsfkramer"
    display_name = "Herbert Smith Freehills Kramer"
    enabled = True

    careers_url = "https://careers.hsfkramer.com/global/en/search-results"

    default_config = {
        "source_url": careers_url,
        "page_size": 10,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = self.plugin_config.get("source_url")
        if not source_url:
            raise ValueError("Plugin requires 'source_url'")

        page_size = int(self.plugin_config.get("page_size", 10))

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
            }
        )

        jobs: list[dict[str, Any]] = []
        seen_references: set[str] = set()

        offset = 0
        total_hits: int | None = None

        while total_hits is None or offset < total_hits:
            response = session.get(
                source_url,
                params={"from": offset},
                timeout=30,
            )
            response.raise_for_status()

            search_data = self._extract_search_data(response.text)

            page_jobs = search_data.get("data", {}).get("jobs", [])
            total_hits = int(search_data.get("totalHits", 0))

            print(
                f"HSF Kramer: offset={offset}, "
                f"received={len(page_jobs)}, total={total_hits}"
            )

            if not page_jobs:
                break

            for item in page_jobs:
                reference = (
                    item.get("reqId")
                    or item.get("jobId")
                    or item.get("jobSeqNo")
                )

                if not reference or reference in seen_references:
                    continue

                seen_references.add(reference)

                job_seq_no = item.get("jobSeqNo")
                title = item.get("title", "").strip()

                jobs.append(
                    {
                        "job_url": self._build_job_url(
                            source_url=source_url,
                            job_seq_no=job_seq_no,
                            title=title,
                        ),
                        "firm_name": self.firm_name,
                        "title": title,
                        "office_location": (
                            item.get("location")
                            or item.get("cityStateCountry")
                            or item.get("cityState")
                        ),
                        "practice_area": (
                            item.get("category")
                            or self._get_raw_category(item)
                        ),
                        "pqe_level": None,
                        "description": item.get("descriptionTeaser"),
                        "source_reference": reference,
                        "status": "LIVE",
                        "extra_info": {
                            "source": "phenom_embedded_json",
                            "job_id": item.get("jobId"),
                            "req_id": item.get("reqId"),
                            "job_seq_no": job_seq_no,
                            "posted_date": item.get("postedDate"),
                            "job_type": item.get("type"),
                            "apply_url": item.get("applyUrl"),
                            "country": item.get("country"),
                            "city": item.get("city"),
                            "state": item.get("state"),
                        },
                    }
                )

            offset += page_size

        return jobs

    @staticmethod
    def _extract_search_data(html: str) -> dict[str, Any]:
        """
        Extract the phApp.ddo JSON object and return eagerLoadRefineSearch.
        """

        match = re.search(
            r"phApp\.ddo\s*=\s*(\{.*?\});\s*"
            r"phApp\.experimentData",
            html,
            flags=re.DOTALL,
        )

        if not match:
            raise ValueError("Could not find phApp.ddo JSON in HTML response")

        try:
            ddo = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Could not decode phApp.ddo JSON: {exc}"
            ) from exc

        search_data = ddo.get("eagerLoadRefineSearch")

        if not isinstance(search_data, dict):
            raise ValueError(
                "Could not find eagerLoadRefineSearch in phApp.ddo"
            )

        return search_data

    @staticmethod
    def _build_job_url(
        source_url: str,
        job_seq_no: str | None,
        title: str,
    ) -> str:
        if not job_seq_no:
            return source_url

        slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-")

        return (
            "https://careers.hsfkramer.com/global/en/job/"
            f"{job_seq_no}/{slug}"
        )

    @staticmethod
    def _get_raw_category(item: dict[str, Any]) -> str | None:
        categories = item.get("multi_category_array") or []

        if not categories:
            return None

        first_category = categories[0]

        return (
            first_category.get("category_raw")
            or first_category.get("category")
        )