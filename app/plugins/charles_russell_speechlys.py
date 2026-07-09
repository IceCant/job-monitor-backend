from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin
from app.plugins.helper.helper import html_to_text


class CharlesRussellSpeechlysPlugin(BasePlugin):
    plugin_name = "charles_russell_speechlys"
    display_name = "Charles Russell Speechlys"
    enabled = True
    careers_url = "https://www.charlesrussellspeechlys.com/en/careers/current-roles/"
    description = "Charles Russell Speechlys current roles scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "fetch_detail_pages": True,
        "max_pages": 0,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = str(self.plugin_config.get("source_url") or self.careers_url)
        fetch_detail_pages = bool(self.plugin_config.get("fetch_detail_pages", True))
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
        page = 1
        total_pages = 1

        while page <= total_pages:
            if max_pages > 0 and page > max_pages:
                break
            page_url = self._page_url(source_url, page)
            response = session.get(page_url, timeout=timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")
            total_pages = max(total_pages, self._total_pages(soup))

            for result in soup.select("li.roleListingResult"):
                job = self._job_from_listing(result, response.url, page)
                if not job:
                    continue

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

                reference = job["source_reference"]
                if reference in seen:
                    continue
                seen.add(reference)
                jobs.append(job)

            page += 1

        if not jobs:
            raise ValueError("Charles Russell Speechlys current roles page returned no jobs")
        return jobs

    def _job_from_listing(
        self,
        result: Any,
        base_url: str,
        page: int,
    ) -> dict[str, Any] | None:
        title = self._clean_text(result.select_one(".roleListingResultTitle"))
        location = self._clean_text(result.select_one(".roleListingResultLocation"))
        link = result.select_one("a.descriptionlink[href]")
        href = str(link.get("href") or "").strip() if link else ""
        if not title or not href:
            return None

        job_url = urljoin(base_url, href)
        reference = self._reference_from_url(job_url, None)
        return {
            "job_url": job_url,
            "firm_name": self.firm_name,
            "title": title,
            "office_location": location,
            "practice_area": None,
            "pqe_level": self._extract_pqe(title, None),
            "description": None,
            "source_reference": reference,
            "status": "LIVE",
            "extra_info": {
                "source": "charles_russell_speechlys_html",
                "listing_page": page,
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
        title = self._clean_text(soup.select_one("h1.detailPageTitle"))
        description_html = soup.select_one('[data-epi-edit="JobAdvert"]')
        description = html_to_text(str(description_html)) if description_html else None
        fields = self._at_a_glance_fields(soup)
        apply_link = soup.select_one("a.rolePageApply[href]")
        apply_url = urljoin(response.url, str(apply_link.get("href"))) if apply_link else None

        return {
            "title": title,
            "office_location": fields.get("Location"),
            "practice_area": fields.get("Category"),
            "pqe_level": self._extract_pqe(title, description),
            "description": description,
            "source_reference": self._reference_from_url(response.url, apply_url),
            "extra_info": {
                "apply_url": apply_url,
                "contract_type": fields.get("Contract type"),
                "salary": fields.get("Salary"),
                "working_hours": fields.get("Working hours"),
                "description_source": "detail_page" if description else None,
            },
        }

    @classmethod
    def _at_a_glance_fields(cls, soup: BeautifulSoup) -> dict[str, str]:
        fields: dict[str, str] = {}
        for term in soup.select("aside dt"):
            key = cls._clean_text(term)
            sibling = term.find_next_sibling("dd")
            value = cls._clean_text(sibling)
            if key and value:
                fields[key] = value
        return fields

    @staticmethod
    def _page_url(source_url: str, page: int) -> str:
        if page <= 1:
            return source_url
        parsed = urlparse(source_url)
        query = parse_qs(parsed.query)
        query["page"] = [str(page)]
        return urlunparse(
            parsed._replace(query=urlencode(query, doseq=True), fragment="")
        )

    @staticmethod
    def _total_pages(soup: BeautifulSoup) -> int:
        text = soup.select_one(".searchPagePaginationInfo")
        match = re.search(
            r"Page\s+\d+\s+of\s+(\d+)",
            text.get_text(" ", strip=True) if text else "",
            flags=re.IGNORECASE,
        )
        return int(match.group(1)) if match else 1

    @classmethod
    def _reference_from_url(cls, job_url: str, apply_url: str | None) -> str:
        if apply_url:
            match = re.search(r"/([^/?#]+CRS)(?:[/?#]|$)", apply_url, flags=re.IGNORECASE)
            if match:
                return match.group(1)
        path = urlparse(job_url).path.rstrip("/")
        return path.rsplit("/", 1)[-1] or job_url

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
        return CharlesRussellSpeechlysPlugin._clean(element.get_text(" ", strip=True))

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None
