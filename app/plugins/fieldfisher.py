from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin
from app.plugins.helper.helper import html_to_text


class FieldfisherPlugin(BasePlugin):
    plugin_name = "fieldfisher"
    display_name = "Fieldfisher"
    enabled = True
    careers_url = (
        "https://fieldfisher.current-vacancies.com/"
        "Careers/Fieldfisher%20Vacancy%20Search%20Page-2074"
    )
    description = "Fieldfisher Networx vacancy search scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "page_size": 25,
        "max_pages": 0,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = str(self.plugin_config.get("source_url") or self.careers_url)
        page_size = max(1, int(self.plugin_config.get("page_size", 25)))
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
                "Accept-Language": "en-GB,en;q=0.9",
            }
        )
        landing = session.get(source_url, timeout=timeout)
        landing.raise_for_status()
        soup = BeautifulSoup(landing.text, "lxml")
        form = soup.select_one("form#formVacancySearch")
        token_input = form.select_one('input[name="__RequestVerificationToken"]') if form else None
        if form is None or token_input is None:
            raise ValueError("Fieldfisher vacancy search form was not found")

        token = str(token_input.get("value") or "").strip()
        client_id = self._client_id(landing.text)
        onboarding_page_id = self._onboarding_page_id(landing.text)
        dynamic_field_ids = self._dynamic_field_ids(soup)
        action_url = urljoin(landing.url, str(form.get("action") or "/Careers/SearchVacancies"))
        session.headers.update(
            {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Origin": f"{urlparse(landing.url).scheme}://{urlparse(landing.url).netloc}",
                "Referer": landing.url,
                "X-Requested-With": "XMLHttpRequest",
                "__RequestVerificationToken": token,
            }
        )

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 1
        while True:
            if max_pages > 0 and page > max_pages:
                break
            search_data = {
                "ClientID": client_id,
                "OnboardingPageID": onboarding_page_id,
                "CurrentPage": page,
                "PageSearchResults": True,
                "SearchResultPageSize": page_size,
                "keywords": "",
                "Locations": ["0"],
                "DynamicFields": [
                    {"FieldID": field_id, "FieldValue": ["0"]}
                    for field_id in dynamic_field_ids
                ],
                "SearchResultFields": [],
            }
            response = session.post(
                action_url,
                data={
                    "__RequestVerificationToken": token,
                    "hdnNewWorld": "True",
                    "data": json.dumps(search_data, separators=(",", ":")),
                },
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("OK") is not True:
                raise ValueError("Fieldfisher vacancy search rejected the request")
            items = payload.get("Data") or []
            if not items:
                break

            added = 0
            for item in items:
                title = self._clean(item.get("VacancyTitle"))
                job_url = self._clean(item.get("ApplyLink"))
                if job_url:
                    job_url = urljoin(landing.url, job_url)
                reference = self._reference(item, job_url)
                if not title or not job_url or not reference or reference in seen:
                    continue
                seen.add(reference)
                added += 1
                description = html_to_text(self._clean(item.get("JobDescription")))
                jobs.append(
                    {
                        "job_url": job_url,
                        "firm_name": self.firm_name,
                        "title": title,
                        "office_location": self._clean(item.get("Location")),
                        "practice_area": self._business_area(item),
                        "pqe_level": None,
                        "description": description,
                        "source_reference": reference,
                        "status": "LIVE",
                        "extra_info": {
                            "source": "fieldfisher_networx_json",
                            "listing_page": page,
                            "salary": self._clean(item.get("Salary")),
                            "expiry_date": self._clean(item.get("ExpiryDate")),
                        },
                    }
                )

            if added == 0 or len(items) < page_size:
                break
            page += 1

        if not jobs:
            raise ValueError("Fieldfisher vacancy search returned no jobs")
        return jobs

    @staticmethod
    def _client_id(html: str) -> int:
        match = re.search(r"\bvar\s+cid\s*=\s*(\d+)\s*;", html)
        if not match:
            raise ValueError("Fieldfisher client ID was not found")
        return int(match.group(1))

    @staticmethod
    def _dynamic_field_ids(soup: BeautifulSoup) -> list[str]:
        values: list[str] = []
        for element in soup.select("#search-form-area select[id]"):
            field_id = str(element.get("id") or "").split("_", 1)[0]
            if field_id.isdigit() and field_id not in values:
                values.append(field_id)
        return values

    @staticmethod
    def _onboarding_page_id(html: str) -> int:
        match = re.search(r"InitialiseVacancySearch\(([^)]*)\)", html)
        if not match:
            return 0
        args = [part.strip() for part in match.group(1).split(",")]
        try:
            return int(args[-1])
        except (IndexError, ValueError):
            return 0

    @classmethod
    def _reference(cls, item: dict[str, Any], job_url: str | None) -> str | None:
        direct = cls._clean(item.get("Reference"))
        if direct:
            return direct
        if not job_url:
            return None
        query = parse_qs(urlparse(job_url).query)
        for key in ("id", "vacancyId", "VacancyID"):
            values = query.get(key)
            if values and cls._clean(values[0]):
                return cls._clean(values[0])
        numbers = re.findall(r"\d+", urlparse(job_url).path)
        return numbers[-1] if numbers else urlparse(job_url).path.rstrip("/").rsplit("/", 1)[-1]

    @classmethod
    def _business_area(cls, item: dict[str, Any]) -> str | None:
        for key, value in item.items():
            if "business area" in str(key).replace("_", " ").lower():
                return cls._clean(value)
        return None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None
