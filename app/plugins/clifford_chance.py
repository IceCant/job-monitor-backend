import json
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class CliffordChancePlugin(BasePlugin):
    plugin_name = "clifford_chance"
    display_name = "Clifford Chance"
    enabled = True
    careers_url = "https://jobs.cliffordchance.com/experienced-lawyers"
    description = "Clifford Chance experienced lawyers scraper"
    required_config = ["source_url"]
    default_config = {
        "source_url": careers_url,
        "fetch_detail_pages": True,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = self.plugin_config.get("source_url") or self.careers_url
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

        response = session.get(
            source_url,
            timeout=60,
        )
        self._prepare_response(response)

        soup = BeautifulSoup(response.text, "html.parser")
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        fetch_detail_pages = bool(self.plugin_config.get("fetch_detail_pages", True))

        for card in soup.select(".attrax-vacancy-tile"):
            title_el = card.select_one(".attrax-vacancy-tile__title")
            if title_el is None:
                continue

            title = title_el.get_text(" ", strip=True)
            href = (title_el.get("href") or "").strip()
            job_url = urljoin(source_url, href)
            reference = self._text(card, ".attrax-vacancy-tile__reference-value") or card.get("data-jobid")

            if not title or not reference or reference in seen:
                continue

            seen.add(reference)
            detail = self._fetch_detail(session, job_url) if fetch_detail_pages else {}
            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": detail.get("title") or title,
                    "office_location": detail.get("office_location") or self._text(card, ".attrax-vacancy-tile__location-freetext .attrax-vacancy-tile__item-value")
                    or self._text(card, ".attrax-vacancy-tile__option-location .attrax-vacancy-tile__item-value"),
                    "practice_area": self._text(card, ".attrax-vacancy-tile__option-department .attrax-vacancy-tile__item-value"),
                    "pqe_level": None,
                    "description": detail.get("description") or self._text(card, ".attrax-vacancy-tile__description-value"),
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "attrax_html",
                        "job_id": card.get("data-jobid"),
                        "contract_type": self._text(card, ".attrax-vacancy-tile__option-contract-type .attrax-vacancy-tile__item-value"),
                        "expiry_date": self._text(card, ".attrax-vacancy-tile__expiry-value"),
                        "date_posted": detail.get("date_posted"),
                        "valid_through": detail.get("valid_through"),
                        "description_source": detail.get("description_source") or "listing_card",
                    },
                }
            )

        return jobs

    def _fetch_detail(self, session: requests.Session, job_url: str) -> dict[str, str | None]:
        try:
            response = session.get(job_url, timeout=60)
            self._prepare_response(response)
        except requests.RequestException:
            return {}

        soup = BeautifulSoup(response.text, "html.parser")
        json_ld = self._extract_json_ld(soup)
        description_html = json_ld.get("description") if json_ld else None
        description_source = "json_ld" if description_html else None

        if not description_html:
            description_el = soup.select_one(".description-widget [aria-label='Job description']")
            if description_el is not None:
                description_html = str(description_el)
                description_source = "description_widget"

        description = self._html_to_text(description_html) if description_html else None

        return {
            "title": (json_ld.get("title") or "").strip() if json_ld else None,
            "office_location": self._location_from_json_ld(json_ld) if json_ld else None,
            "description": description,
            "date_posted": json_ld.get("datePosted") if json_ld else None,
            "valid_through": json_ld.get("validThrough") if json_ld else None,
            "description_source": description_source,
        }

    @staticmethod
    def _extract_json_ld(soup: BeautifulSoup) -> dict[str, Any]:
        for script in soup.select("script[type='application/ld+json']"):
            text = script.string or script.get_text()
            if not text:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("@type") == "JobPosting":
                return data
        return {}

    @staticmethod
    def _location_from_json_ld(data: dict[str, Any]) -> str | None:
        locations = data.get("jobLocation")
        if not locations:
            return None
        if not isinstance(locations, list):
            locations = [locations]
        names: list[str] = []
        for item in locations:
            address = item.get("address", {}) if isinstance(item, dict) else {}
            locality = address.get("addressLocality") if isinstance(address, dict) else None
            if locality:
                names.append(str(locality))
        return ", ".join(names) or None

    @staticmethod
    def _html_to_text(html: str | None) -> str | None:
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        for element in soup.select("script, style"):
            element.decompose()
        text = soup.get_text("\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines) or None

    @staticmethod
    def _prepare_response(response: requests.Response) -> None:
        response.raise_for_status()
        response.encoding = "utf-8"

    @staticmethod
    def _text(card, selector: str) -> str | None:
        element = card.select_one(selector)
        if element is None:
            return None
        value = " ".join(element.get_text(" ", strip=True).split())
        return value or None
