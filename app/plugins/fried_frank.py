from typing import Any

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin
from app.plugins.helper.helper import html_to_text


class FriedFrankPlugin(BasePlugin):
    """Scrape Fried Frank attorney vacancies through Greenhouse's public API."""

    plugin_name = "fried_frank"
    display_name = "Fried Frank"
    enabled = True

    careers_url = "https://www.friedfrank.com/careers/attorneyjobopportunities"

    description = "Fried Frank attorney jobs through Greenhouse Job Board API"

    required_config: list[str] = []

    default_config = {
        "board_token": "attorneysfriedfrankharrisshriverjacobsonllp",
        "include_content": True,
        "timeout": 30,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        board_token = self.plugin_config.get(
            "board_token",
            "attorneysfriedfrankharrisshriverjacobsonllp",
        )

        timeout = int(self.plugin_config.get("timeout", 30))
        include_content = bool(
            self.plugin_config.get("include_content", True)
        )

        api_url = (
            "https://boards-api.greenhouse.io/v1/boards/"
            f"{board_token}/jobs"
        )

        response = requests.get(
            api_url,
            params={
                "content": str(include_content).lower(),
            },
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            },
            timeout=timeout,
        )
        response.raise_for_status()

        payload = response.json()
        raw_jobs = payload.get("jobs", [])

        if not isinstance(raw_jobs, list):
            raise ValueError(
                "Unexpected Greenhouse response: 'jobs' is not a list"
            )

        jobs: list[dict[str, Any]] = []
        seen_references: set[str] = set()

        for item in raw_jobs:
            job_id = item.get("id")
            if job_id is None:
                continue

            source_reference = str(job_id)

            if source_reference in seen_references:
                continue

            seen_references.add(source_reference)

            title = clean_text(item.get("title"))
            job_url = clean_text(item.get("absolute_url"))

            if not title or not job_url:
                continue

            departments = extract_names(item.get("departments"))
            offices = extract_names(item.get("offices"))

            location = clean_text(
                (item.get("location") or {}).get("name")
            )

            if not location and offices:
                location = ", ".join(offices)

            description = html_to_text(item.get("content"))

            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": location,
                    "practice_area": (
                        departments[-1]
                        if departments
                        else None
                    ),
                    "pqe_level": extract_pqe(title, description),
                    "description": description,
                    "source_reference": source_reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "greenhouse_api",
                        "greenhouse_job_id": job_id,
                        "internal_job_id": item.get("internal_job_id"),
                        "requisition_id": item.get("requisition_id"),
                        "updated_at": item.get("updated_at"),
                        "language": item.get("language"),
                        "departments": departments,
                        "offices": offices,
                    },
                }
            )

        expected_total = payload.get("meta", {}).get("total")

        if expected_total is not None and len(raw_jobs) != expected_total:
            raise ValueError(
                "Greenhouse returned an incomplete result: "
                f"received {len(raw_jobs)}, expected {expected_total}"
            )

        return jobs


def clean_text(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None

def extract_names(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []

    names: list[str] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        name = clean_text(item.get("name"))

        if name and name not in names:
            names.append(name)

    return names


def extract_pqe(
    title: str | None,
    description: str | None,
) -> str | None:
    """
    Extract simple PQE labels such as:
    - 2-3 PQE
    - 3–5 years
    - third to fifth year
    """

    import re

    searchable = " ".join(
        part for part in [title, description] if part
    )

    patterns = [
        r"\b\d+\s*[-–—]\s*\d+\s*PQE\b",
        r"\b\d+\+?\s*PQE\b",
        r"\b\d+\s*[-–—]\s*\d+\s+years?\b",
        r"\b\d+\+\s+years?\b",
        (
            r"\b(?:first|second|third|fourth|fifth|sixth|seventh|"
            r"eighth|ninth|tenth)"
            r"\s*[-–—]?\s*(?:to\s+)?"
            r"(?:first|second|third|fourth|fifth|sixth|seventh|"
            r"eighth|ninth|tenth)?\s*year\b"
        ),
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            searchable,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(0).strip()

    return None