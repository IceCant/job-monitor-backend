from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

from app.plugins.base import BasePlugin


class SuccessFactorsPlugin(BasePlugin):
    """Shared scraper for SAP SuccessFactors careers sites."""

    plugin_name = "successfactors"
    display_name = "SuccessFactors"
    discoverable = False
    required_config = ["source_url"]
    listing_style = "tiles"
    page_mode = "query"
    page_size = 25
    source_name = "successfactors_html"
    default_config = {
        "max_pages": 0,
        "safety_max_pages": 50,
        "fetch_detail_pages": False,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = self.plugin_config.get("source_url") or self.careers_url
        if not source_url:
            raise ValueError("SuccessFactors plugin requires source_url")

        timeout = int(self.plugin_config.get("timeout", 60))
        max_pages = int(self.plugin_config.get("max_pages", 0))
        safety_max_pages = int(self.plugin_config.get("safety_max_pages", 50))
        fetch_details = bool(self.plugin_config.get("fetch_detail_pages", False))

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
        offset = 0
        page = 1
        total: int | None = None

        while page <= safety_max_pages:
            if max_pages > 0 and page > max_pages:
                break

            page_url = self._page_url(str(source_url), offset)
            response = session.get(page_url, timeout=timeout)
            response.raise_for_status()
            response.encoding = "utf-8"
            soup = BeautifulSoup(response.text, "html.parser")

            if not self._has_results_structure(soup):
                raise ValueError(f"{self.display_name} SuccessFactors results structure was not found")

            if total is None:
                total = self._total_results(soup)

            listings = self._listings(soup)
            if not listings:
                break

            new_jobs = 0
            for listing in listings:
                reference = listing["reference"]
                if reference in seen:
                    continue
                seen.add(reference)
                new_jobs += 1

                detail = (
                    self._fetch_detail(session, listing["job_url"], timeout)
                    if fetch_details or not listing.get("office_location")
                    else {}
                )
                description = detail.get("description")
                jobs.append(
                    {
                        "job_url": listing["job_url"],
                        "firm_name": self.firm_name,
                        "title": detail.get("title") or listing["title"],
                        "office_location": detail.get("office_location") or listing.get("office_location"),
                        "practice_area": detail.get("practice_area"),
                        "pqe_level": self._extract_pqe(listing["title"], description),
                        "description": description,
                        "source_reference": reference,
                        "status": "LIVE",
                        "extra_info": {
                            "source": self.source_name,
                            "listing_page": page,
                            "date_posted": detail.get("date_posted"),
                            "postal_code": listing.get("postal_code"),
                        },
                    }
                )

            offset += len(listings)
            page += 1
            if new_jobs == 0 or len(listings) < self.page_size:
                break
            if total is not None and offset >= total:
                break

        return jobs

    def _page_url(self, source_url: str, offset: int) -> str:
        if self.page_mode == "path":
            base = source_url.split("?", 1)[0].rstrip("/")
            return f"{base}/{offset}/" if offset else f"{base}/"

        parsed = urlparse(source_url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if offset:
            params["startrow"] = str(offset)
        return urlunparse(parsed._replace(query=urlencode(params)))

    def _has_results_structure(self, soup: BeautifulSoup) -> bool:
        selector = "#job-tile-list" if self.listing_style == "tiles" else "#searchresults"
        return soup.select_one(selector) is not None

    def _listings(self, soup: BeautifulSoup) -> list[dict[str, str | None]]:
        if self.listing_style == "table":
            return self._table_listings(soup)
        return self._tile_listings(soup)

    def _tile_listings(self, soup: BeautifulSoup) -> list[dict[str, str | None]]:
        listings: list[dict[str, str | None]] = []
        for tile in soup.select("#job-tile-list > li.job-tile"):
            link = tile.select_one(".sub-section-desktop a.jobTitle-link") or tile.select_one("a.jobTitle-link")
            href = self._clean(link.get("href")) if link else None
            title = self._clean(link.get_text(" ", strip=True)) if link else None
            reference = self._reference(href)
            if not href or not title or not reference:
                continue
            listings.append(
                {
                    "reference": reference,
                    "title": title,
                    "job_url": urljoin(self.careers_url or "", href),
                    "office_location": self._text(tile, ".sub-section-desktop .section-field.city div[id$='-value']"),
                    "postal_code": self._text(tile, ".sub-section-desktop .section-field.zip div[id$='-value']"),
                }
            )
        return listings

    def _table_listings(self, soup: BeautifulSoup) -> list[dict[str, str | None]]:
        listings: list[dict[str, str | None]] = []
        for row in soup.select("#searchresults tbody tr.data-row"):
            link = row.select_one(".jobTitle.hidden-phone a.jobTitle-link") or row.select_one("a.jobTitle-link")
            href = self._clean(link.get("href")) if link else None
            title = self._clean(link.get_text(" ", strip=True)) if link else None
            reference = self._reference(href)
            if not href or not title or not reference:
                continue
            listings.append(
                {
                    "reference": reference,
                    "title": title,
                    "job_url": urljoin(self.careers_url or "", href),
                    "office_location": self._text(row, "td.colLocation .jobLocation"),
                    "postal_code": None,
                }
            )
        return listings

    def _fetch_detail(
        self, session: requests.Session, job_url: str, timeout: int
    ) -> dict[str, str | None]:
        try:
            response = session.get(job_url, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException:
            return {}

        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
        description = soup.select_one("[itemprop='description'] .jobdescription")
        if description is None:
            description = soup.select_one("[itemprop='description']")
        date_meta = soup.select_one("meta[itemprop='datePosted']")

        return {
            "title": self._text(soup, "[itemprop='title']"),
            "office_location": self._text(soup, ".jobGeoLocation"),
            "practice_area": self._text(soup, "[data-careersite-propertyid='dept']"),
            "description": self._html_to_text(description),
            "date_posted": self._clean(date_meta.get("content")) if date_meta else None,
        }

    @staticmethod
    def _total_results(soup: BeautifulSoup) -> int | None:
        label = soup.select_one("#tile-search-results-label") or soup.select_one(".paginationLabel")
        text = label.get_text(" ", strip=True) if label else ""
        match = re.search(r"\bof\s+(\d+)\b", text, re.IGNORECASE)
        return int(match.group(1)) if match else None

    @staticmethod
    def _reference(href: str | None) -> str | None:
        match = re.search(r"/(\d+)/?(?:\?|$)", href or "")
        return match.group(1) if match else None

    @staticmethod
    def _extract_pqe(title: str, description: str | None) -> str | None:
        text = f"{title} {description or ''}"
        match = re.search(
            r"(\d+\s*(?:(?:[-\u2013]|to)\s*\d+|\+)?\s*PQE\+?)",
            text,
            re.IGNORECASE,
        )
        return " ".join(match.group(1).split()) if match else None

    @classmethod
    def _html_to_text(cls, element: Tag | None) -> str | None:
        if element is None:
            return None
        for child in element.select("script, style"):
            child.decompose()
        lines = [cls._clean(line) for line in element.get_text("\n", strip=True).splitlines()]
        return "\n".join(line for line in lines if line) or None

    @classmethod
    def _text(cls, root: BeautifulSoup | Tag, selector: str) -> str | None:
        element = root.select_one(selector)
        return cls._clean(element.get_text(" ", strip=True)) if element else None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None
