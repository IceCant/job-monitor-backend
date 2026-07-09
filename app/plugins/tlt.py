from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin
from app.plugins.helper.helper import html_to_text


class TLTPlugin(BasePlugin):
    plugin_name = "tlt"
    display_name = "TLT"
    enabled = True
    careers_url = "https://apply.tlt.com/vacancies/#results"
    description = "TLT public vacancies scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "fetch_detail_pages": False,
        "max_pages": 0,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = str(self.plugin_config.get("source_url") or self.careers_url)
        fetch_detail_pages = bool(self.plugin_config.get("fetch_detail_pages", False))
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
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-GB,en;q=0.9",
            }
        )

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        page_url = source_url
        page = 1

        while page_url:
            if max_pages > 0 and page > max_pages:
                break

            response = session.get(page_url, timeout=timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            for card in soup.select("#peopleList .bio"):
                job = self._job_from_card(card, response.url)
                if not job:
                    continue
                reference = job["source_reference"]
                if reference in seen:
                    continue
                seen.add(reference)

                if fetch_detail_pages:
                    detail = self._detail(session, job["job_url"], timeout)
                    job.update(
                        {
                            "title": detail.get("title") or job["title"],
                            "office_location": detail.get("office_location")
                            or job["office_location"],
                            "practice_area": detail.get("practice_area")
                            or job["practice_area"],
                            "pqe_level": detail.get("pqe_level") or job["pqe_level"],
                            "description": detail.get("description"),
                            "source_reference": detail.get("source_reference")
                            or job["source_reference"],
                        }
                    )
                    job["extra_info"].update(detail.get("extra_info") or {})

                job["extra_info"]["listing_page"] = page
                jobs.append(job)

            next_url = self._next_page_url(soup, response.url)
            if not next_url or next_url == page_url:
                break
            page_url = next_url
            page += 1

        if not jobs:
            raise ValueError("TLT vacancies page returned no jobs")
        return jobs

    def _job_from_card(self, card: Any, base_url: str) -> dict[str, Any] | None:
        title = self._clean_text(card.select_one(".vacancy_title"))
        link = card.select_one(".bio-contact a[href]")
        href = str(link.get("href") or "").strip() if link else ""
        if not title or not href:
            return None

        job_url = urljoin(base_url, href)
        reference = self._reference_from_url(job_url)
        if not reference:
            return None

        location = self._clean_text(card.select_one(".value_location"))
        contract_type = self._clean_text(card.select_one(".value_contract_type"))
        salary = self._clean_text(card.select_one(".value_salary"))
        category = self._category_from_card(card)

        return {
            "job_url": job_url,
            "firm_name": self.firm_name,
            "title": title,
            "office_location": location,
            "practice_area": category,
            "pqe_level": self._extract_pqe(title, None),
            "description": None,
            "source_reference": reference,
            "status": "LIVE",
            "extra_info": {
                "source": "tlt_html",
                "contract_type": contract_type,
                "salary": salary,
            },
        }

    def _detail(
        self,
        session: requests.Session,
        job_url: str,
        timeout: int,
    ) -> dict[str, Any]:
        try:
            response = session.get(job_url, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException:
            return {}

        soup = BeautifulSoup(response.text, "lxml")
        posting = self._job_posting_json(soup)
        title = self._clean(posting.get("title")) if posting else None
        description = html_to_text(self._clean(posting.get("description"))) if posting else None
        location = self._location_from_posting(posting) if posting else None
        reference = self._reference_from_posting(posting) if posting else None
        sidebar = self._sidebar_fields(soup)

        return {
            "title": title,
            "office_location": location or sidebar.get("Location"),
            "practice_area": sidebar.get("Job Category"),
            "pqe_level": self._extract_pqe(title, description),
            "description": description,
            "source_reference": reference or sidebar.get("Reference"),
            "extra_info": {
                "date_posted": self._clean(posting.get("datePosted")) if posting else None,
                "valid_through": self._clean(posting.get("validThrough")) if posting else None,
                "employment_type": self._clean(posting.get("employmentType")) if posting else None,
                "contract_type": sidebar.get("Contract Type"),
                "salary": sidebar.get("Salary") or self._salary_from_posting(posting),
                "closing_date": sidebar.get("Closing Date"),
                "description_source": "json_ld" if description else None,
            },
        }

    @classmethod
    def _next_page_url(cls, soup: BeautifulSoup, base_url: str) -> str | None:
        next_item = soup.select_one("ul.pagination li.next:not(.disabled) a[href]")
        if next_item is None:
            return None
        href = str(next_item.get("href") or "").strip()
        return urljoin(base_url, href) if href else None

    @classmethod
    def _job_posting_json(cls, soup: BeautifulSoup) -> dict[str, Any] | None:
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or script.get_text() or "{}")
            except json.JSONDecodeError:
                continue
            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if isinstance(item, dict) and item.get("@type") == "JobPosting":
                    return item
        return None

    @classmethod
    def _sidebar_fields(cls, soup: BeautifulSoup) -> dict[str, str]:
        fields: dict[str, str] = {}
        for row in soup.select("#vacancy-sidebar-fields > div"):
            class_names = row.get("class") or []
            value_element = row.select_one(".vacancy-value")
            value = cls._clean_text(value_element)
            if not value:
                continue
            for class_name in class_names:
                if not str(class_name).startswith("field_"):
                    continue
                key = str(class_name).removeprefix("field_").replace("_", " ").title()
                fields[key] = value
        return fields

    @classmethod
    def _category_from_card(cls, card: Any) -> str | None:
        media = card.select_one(".bio-media")
        if media is None:
            return None
        for class_name in media.get("class") or []:
            value = str(class_name)
            if value.startswith("category_"):
                return value.removeprefix("category_").replace("_", " ").title()
        return None

    @classmethod
    def _reference_from_url(cls, job_url: str) -> str | None:
        match = re.search(r"/vacancies/(\d+)(?:/|$)", urlparse(job_url).path)
        return f"TLT-{match.group(1)}" if match else None

    @classmethod
    def _reference_from_posting(cls, posting: dict[str, Any] | None) -> str | None:
        if not isinstance(posting, dict):
            return None
        identifier = posting.get("identifier")
        if isinstance(identifier, dict):
            value = cls._clean(identifier.get("value"))
            return f"TLT-{value}" if value and not value.startswith("TLT-") else value
        return cls._clean(identifier)

    @classmethod
    def _location_from_posting(cls, posting: dict[str, Any] | None) -> str | None:
        if not isinstance(posting, dict):
            return None
        locations = posting.get("jobLocation")
        if isinstance(locations, dict):
            locations = [locations]
        if not isinstance(locations, list):
            return None

        values: list[str] = []
        for location in locations:
            if not isinstance(location, dict):
                continue
            address = location.get("address")
            if isinstance(address, dict):
                value = cls._clean(address.get("addressLocality"))
                if value and value not in values:
                    values.append(value)
        return ", ".join(values) or None

    @classmethod
    def _salary_from_posting(cls, posting: dict[str, Any] | None) -> str | None:
        if not isinstance(posting, dict):
            return None
        salary = posting.get("baseSalary")
        if not isinstance(salary, dict):
            return None
        value = salary.get("value")
        if isinstance(value, dict):
            value = value.get("value")
        return cls._clean(value)

    @staticmethod
    def _extract_pqe(title: str | None, description: str | None) -> str | None:
        text = f"{title or ''} {description or ''}"
        match = re.search(
            r"\b(?:NQ|\d+(?:\s*(?:-|\u2013|to)\s*\d+)?\+?\s*PQE)\b",
            text,
            flags=re.IGNORECASE,
        )
        return " ".join(match.group(0).split()) if match else None

    @staticmethod
    def _clean_text(element: Any) -> str | None:
        if element is None:
            return None
        return TLTPlugin._clean(element.get_text(" ", strip=True))

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None
