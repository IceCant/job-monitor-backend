from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

from app.plugins.base import BasePlugin


class WithersPlugin(BasePlugin):
    plugin_name = "withers"
    display_name = "Withers"
    enabled = True
    careers_url = "https://www.witherscareers.com/"
    description = "Withers Reach ATS careers scraper"
    required_config = ["source_url"]
    default_config = {
        "source_url": careers_url,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = self.plugin_config.get("source_url") or self.careers_url
        timeout = int(self.plugin_config.get("timeout", 60))

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

        response = session.get(source_url, timeout=timeout)
        response.raise_for_status()
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
        listing = soup.select_one("#job-listing")
        if listing is None:
            raise ValueError("Withers job listing structure was not found")

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for card in listing.select("section[id^='vacancy_']"):
            reference = self._reference(card)
            title_link = card.select_one("h2 a[href*='job-detail.php']")
            title = self._text(title_link)
            href = self._clean(title_link.get("href")) if title_link else None
            if not reference or not title or not href or reference in seen:
                continue
            seen.add(reference)

            practice_area, location, contract_type = self._metadata(card)
            jobs.append(
                {
                    "job_url": urljoin(str(source_url), href),
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": location,
                    "practice_area": practice_area,
                    "pqe_level": self._extract_pqe(title),
                    "description": self._summary(card),
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "withers_reach_html",
                        "contract_type": contract_type,
                        "apply_url": self._apply_url(card),
                    },
                }
            )

        return jobs

    @classmethod
    def _metadata(cls, card: Tag) -> tuple[str | None, str | None, str | None]:
        for paragraph in card.select(".text > p"):
            text = cls._text(paragraph)
            if not text or "|" not in text:
                continue
            parts = [cls._clean(part) for part in text.split("|")]
            if len(parts) >= 3:
                return parts[0], parts[1], parts[2]
        return None, None, None

    @classmethod
    def _summary(cls, card: Tag) -> str | None:
        for paragraph in card.select(".text > p"):
            text = cls._text(paragraph)
            if not text or "|" in text or "Apply Now" in text:
                continue
            text = re.sub(r"\s*More Information\s*>>\s*$", "", text, flags=re.IGNORECASE)
            return cls._clean(text)
        return None

    @classmethod
    def _apply_url(cls, card: Tag) -> str | None:
        link = card.select_one("a[href*='candidate.witherscareers.com']")
        return cls._clean(link.get("href")) if link else None

    @staticmethod
    def _reference(card: Tag) -> str | None:
        match = re.fullmatch(r"vacancy_(\d+)", str(card.get("id") or ""))
        return match.group(1) if match else None

    @staticmethod
    def _extract_pqe(title: str) -> str | None:
        match = re.search(
            r"(\d+\s*(?:(?:[-\u2013]|to)\s*\d+|\+)?\s*PQE\+?)",
            title,
            re.IGNORECASE,
        )
        if match:
            return " ".join(match.group(1).split())

        year_match = re.search(
            r"(\d+(?:st|nd|rd|th)\s*[-\u2013]\s*\d+(?:st|nd|rd|th)\s+year)",
            title,
            re.IGNORECASE,
        )
        return " ".join(year_match.group(1).split()) if year_match else None

    @classmethod
    def _text(cls, element: Tag | None) -> str | None:
        return cls._clean(element.get_text(" ", strip=True)) if element else None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None
