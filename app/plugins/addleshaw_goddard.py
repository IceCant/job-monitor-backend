from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

from app.plugins.base import BasePlugin


class AddleshawGoddardPlugin(BasePlugin):
    plugin_name = "addleshaw_goddard"
    display_name = "Addleshaw Goddard"
    enabled = True
    careers_url = "https://joinus.addleshawgoddard.com/jobs/search"
    description = "Addleshaw Goddard Clinch careers scraper"
    required_config = ["source_url"]
    default_config = {
        "source_url": careers_url,
        "max_pages": 0,
        "safety_max_pages": 50,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = self.plugin_config.get("source_url") or self.careers_url
        timeout = int(self.plugin_config.get("timeout", 60))
        max_pages = int(self.plugin_config.get("max_pages", 0))
        safety_max_pages = int(self.plugin_config.get("safety_max_pages", 50))

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                )
            }
        )

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 1
        total: int | None = None

        while page <= safety_max_pages:
            if max_pages > 0 and page > max_pages:
                break

            response = session.get(self._page_url(str(source_url), page), timeout=timeout)
            response.raise_for_status()
            response.encoding = "utf-8"
            soup = BeautifulSoup(response.text, "html.parser")
            results = soup.select_one(".job-search-results-content")
            if results is None:
                raise ValueError("Addleshaw Goddard job results structure was not found")

            if total is None:
                total = self._total_results(soup)

            cards = results.select("article.job-search-results-card-col")
            if not cards:
                break

            new_jobs = 0
            for card in cards:
                link = card.select_one(".job-search-results-card-title a")
                title = self._text(link)
                job_url = self._clean(link.get("href")) if link else None
                reference = self._reference(card, job_url)
                if not title or not job_url or not reference or reference in seen:
                    continue
                seen.add(reference)
                new_jobs += 1

                locations = self._unique_text(card.select(".job-component-location span"))
                jobs.append(
                    {
                        "job_url": job_url,
                        "firm_name": self.firm_name,
                        "title": title,
                        "office_location": "; ".join(locations) or None,
                        "practice_area": self._text(card.select_one(".job-component-department span")),
                        "pqe_level": self._extract_pqe(title),
                        "description": None,
                        "source_reference": reference,
                        "status": "LIVE",
                        "extra_info": {
                            "source": "addleshaw_goddard_clinch_html",
                            "listing_page": page,
                            "vacancy_type": self._text(card.select_one(".job-component-dropdown-field-1 span")),
                            "contract_type": self._text(card.select_one(".job-component-dropdown-field-2 span")),
                            "employment_type": self._text(card.select_one(".job-component-dropdown-field-3 span")),
                        },
                    }
                )

            page += 1
            if new_jobs == 0 or (total is not None and len(jobs) >= total):
                break

        return jobs

    @staticmethod
    def _page_url(source_url: str, page: int) -> str:
        parsed = urlparse(source_url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        params["page"] = str(page)
        return urlunparse(parsed._replace(query=urlencode(params)))

    @classmethod
    def _reference(cls, card: Tag, job_url: str | None) -> str | None:
        details = card.select_one("[class*='job-component-details-']")
        if details:
            for class_name in details.get("class", []):
                if class_name.startswith("job-component-details-"):
                    return class_name.removeprefix("job-component-details-")
        return (job_url or "").rstrip("/").rsplit("/", 1)[-1] or None

    @staticmethod
    def _total_results(soup: BeautifulSoup) -> int | None:
        counts = soup.select_one(".table-counts")
        text = counts.get_text(" ", strip=True) if counts else ""
        match = re.search(r"\bof\s+(\d+)\s+in\s+total\b", text, re.IGNORECASE)
        return int(match.group(1)) if match else None

    @staticmethod
    def _extract_pqe(title: str) -> str | None:
        match = re.search(
            r"(\d+\s*(?:(?:[-\u2013]|to)\s*\d+|\+)?\s*PQE\+?)",
            title,
            re.IGNORECASE,
        )
        return " ".join(match.group(1).split()) if match else None

    @classmethod
    def _unique_text(cls, elements: list[Tag]) -> list[str]:
        values: list[str] = []
        for element in elements:
            value = cls._text(element)
            if value and value not in values:
                values.append(value)
        return values

    @classmethod
    def _text(cls, element: Tag | None) -> str | None:
        return cls._clean(element.get_text(" ", strip=True)) if element else None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None
