from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class AOShearmanPlugin(BasePlugin):
    plugin_name = "ao_shearman"
    display_name = "A&O Shearman"
    enabled = True
    careers_url = (
        "https://careers.aoshearman.com/en/search-jobs"
        "?acm=ALL"
        "&alrpm=2635167-6269131-2648110-2643743"
        "&ascf=%5b%7B%22key%22:%22ALL%22,%22value%22:%22%22%7D%5d"
    )
    description = "A&O Shearman Radancy careers scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "results_url": "https://careers.aoshearman.com/en/search-jobs/results",
        "records_per_page": 100,
        "resolve_multiple_locations": True,
        "max_pages": 0,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = str(self.plugin_config.get("source_url") or self.careers_url)
        results_url = str(self.plugin_config.get("results_url") or self.default_config["results_url"])
        timeout = int(self.plugin_config.get("timeout", 60))
        max_pages = int(self.plugin_config.get("max_pages", 0))
        records_per_page = int(self.plugin_config.get("records_per_page", 100))
        resolve_multiple_locations = self._bool(self.plugin_config.get("resolve_multiple_locations", True))

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                "Accept": "*/*",
                "Content-Type": "application/json; charset=utf-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": source_url,
            }
        )

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        total_pages: int | None = None
        page = 1

        while True:
            if max_pages > 0 and page > max_pages:
                break
            if total_pages is not None and page > total_pages:
                break

            response = session.get(
                results_url,
                params=self._api_params(page, records_per_page),
                timeout=timeout,
            )
            response.raise_for_status()
            response.encoding = "utf-8"

            soup = BeautifulSoup(self._results_html(response), "html.parser")
            total_pages = total_pages or self._total_pages(soup)
            before = len(jobs)
            self._append_jobs(
                soup,
                results_url,
                page,
                jobs,
                seen,
                session,
                timeout,
                resolve_multiple_locations,
            )
            if len(jobs) == before:
                break
            page += 1

        return jobs

    def _append_jobs(
        self,
        soup: BeautifulSoup,
        page_url: str,
        page: int,
        jobs: list[dict[str, Any]],
        seen: set[str],
        session: requests.Session,
        timeout: int,
        resolve_multiple_locations: bool,
    ) -> None:
        for item in soup.select("li.search-results-list__item"):
            link = item.select_one("a.search-results-list__job-link[href]")
            if link is None:
                continue

            href = str(link.get("href") or "").strip()
            title = self._clean(link.get_text(" ", strip=True))
            job_url = urljoin(page_url, href)
            reference = self._reference(link, job_url)
            if not href or not title or not reference or reference in seen:
                continue

            location = self._text(item, ".job-location")
            location_source = "listing"
            if resolve_multiple_locations and (location or "").lower() == "multiple locations":
                detail_location = self._detail_location(session, job_url, timeout)
                if detail_location:
                    location = detail_location
                    location_source = "detail_page"

            seen.add(reference)
            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": location,
                    "practice_area": None,
                    "pqe_level": None,
                    "description": None,
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "aoshearman_radancy_api",
                        "listing_page": page,
                        "brand_name": self._text(item, ".brand-name"),
                        "location_source": location_source,
                    },
                }
            )

    @staticmethod
    def _api_params(page: int, records_per_page: int) -> dict[str, Any]:
        return {
            "CurrentPage": page,
            "RecordsPerPage": max(1, records_per_page),
            "Distance": 50,
            "RadiusUnitType": 0,
            "Keywords": "",
            "Location": "",
            "ShowRadius": "False",
            "IsPagination": "True" if page > 1 else "False",
            "CustomFacetName": "",
            "FacetTerm": "",
            "FacetType": 0,
            "SearchResultsModuleName": "Section 6 - Search Results List",
            "SearchFiltersModuleName": "Section 6 - Search Filters",
            "SortCriteria": 0,
            "SortDirection": 0,
            "SearchType": 6,
            "PostalCode": "",
            "ResultsType": 0,
        }

    @staticmethod
    def _results_html(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text
        if isinstance(payload, dict):
            results = payload.get("results")
            if isinstance(results, str):
                return results
        return response.text

    @classmethod
    def _detail_location(
        cls,
        session: requests.Session,
        job_url: str,
        timeout: int,
    ) -> str | None:
        try:
            response = session.get(job_url, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException:
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        personalized_locations = cls._personalized_locations(soup)
        if personalized_locations:
            return personalized_locations

        detail_location = cls._text(soup, ".job-detail-location")
        if detail_location and detail_location.lower() != "multiple locations":
            return cls._normalize_location(detail_location)
        return cls._jsonld_location(soup)

    @classmethod
    def _personalized_locations(cls, soup: BeautifulSoup) -> str | None:
        element = soup.select_one("#Pe_Locations[value]")
        raw = str(element.get("value") or "") if element else ""
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(payload, list):
            return None

        locations: list[str] = []
        seen: set[str] = set()
        for item in payload:
            if not isinstance(item, dict):
                continue
            location = cls._normalize_location(item.get("FormattedName"))
            if location and location not in seen:
                locations.append(location)
                seen.add(location)
        return "; ".join(cls._compact_locations(locations)) or None

    @staticmethod
    def _compact_locations(locations: list[str]) -> list[str]:
        compacted: list[str] = []
        for location in locations:
            normalized = location.lower()
            if any(location != other and normalized in other.lower() for other in locations):
                continue
            compacted.append(location)
        return compacted

    @classmethod
    def _jsonld_location(cls, soup: BeautifulSoup) -> str | None:
        for script in soup.select("script[type='application/ld+json']"):
            raw = script.string or script.get_text()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(payload, dict) or payload.get("@type") != "JobPosting":
                continue

            locations = cls._jsonld_locations(payload.get("jobLocation"))
            if locations:
                return "; ".join(locations)
        return None

    @classmethod
    def _jsonld_locations(cls, raw_locations: Any) -> list[str]:
        if isinstance(raw_locations, dict):
            iterable = [raw_locations]
        elif isinstance(raw_locations, list):
            iterable = raw_locations
        else:
            return []

        locations: list[str] = []
        seen: set[str] = set()
        for item in iterable:
            if not isinstance(item, dict):
                continue
            address = item.get("address")
            if not isinstance(address, dict):
                continue
            parts = [
                cls._clean(address.get("addressLocality")),
                cls._clean(address.get("addressRegion")),
                cls._clean(address.get("addressCountry")),
            ]
            location = cls._normalize_location(", ".join(part for part in parts if part))
            if location and location not in seen:
                locations.append(location)
                seen.add(location)
        return locations

    @staticmethod
    def _total_pages(soup: BeautifulSoup) -> int:
        container = soup.select_one("[data-selector-name='searchresults']") or soup.select_one("[data-total-pages]")
        value = container.get("data-total-pages") if container else None
        try:
            pages = int(str(value or "1"))
        except ValueError:
            pages = 1
        return max(pages, 1)

    @classmethod
    def _reference(cls, link: Any, job_url: str) -> str | None:
        data_id = cls._clean(link.get("data-job-id"))
        if data_id:
            return data_id

        parts = [part for part in urlparse(job_url).path.split("/") if part]
        for part in reversed(parts):
            if part.isdigit():
                return part

        match = re.search(r"(\d{6,})", job_url)
        return match.group(1) if match else None

    @classmethod
    def _text(cls, root: Any, selector: str) -> str | None:
        element = root.select_one(selector) if root else None
        if element is None:
            return None
        return cls._clean(element.get_text(" ", strip=True))

    @classmethod
    def _normalize_location(cls, value: str | None) -> str | None:
        text = cls._clean(value)
        if not text:
            return None

        normalized_segments: list[str] = []
        for segment in text.split(";"):
            parts = [part.strip() for part in segment.split(",") if part.strip()]
            while len(parts) > 2 and parts[-1] in parts[:-1]:
                parts.pop()
            normalized = ", ".join(parts) if parts else cls._clean(segment)
            if normalized:
                normalized_segments.append(normalized)
        return "; ".join(normalized_segments) or None

    @staticmethod
    def _bool(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None
