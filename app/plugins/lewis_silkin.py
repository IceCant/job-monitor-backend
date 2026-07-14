from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class LewisSilkinPlugin(BasePlugin):
    plugin_name = "lewis_silkin"
    display_name = "Lewis Silkin"
    enabled = True
    careers_url = "https://www.lewissilkin.com/life-at-ls/careers/vacancies"
    description = "Lewis Silkin vacancies page / AllHires feed scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "timeout": 30,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = str(self.plugin_config.get("source_url") or self.careers_url)
        timeout = int(self.plugin_config.get("timeout", 30))

        response = requests.get(
            source_url,
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                )
            },
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        jobs = self._jobs_from_next_data(soup)
        if not jobs:
            jobs = self._jobs_from_cards(soup)
        if not jobs:
            raise ValueError("Lewis Silkin vacancies page returned no jobs")
        return jobs

    def _jobs_from_next_data(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        script = soup.select_one("script#__NEXT_DATA__")
        if script is None or not script.string:
            return []

        try:
            payload = json.loads(script.string)
        except json.JSONDecodeError:
            return []

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for fields in self._walk_allhires_fields(payload):
            reference = self._clean(self._field_value(fields, "ID"))
            job_url = self._clean(self._field_value(fields, "Link"))
            title = self._clean(self._field_value(fields, "RoleTitle"))
            if not reference:
                reference = self._reference_from_url(job_url)
            if not reference or not title or not job_url or reference in seen:
                continue

            seen.add(reference)
            description = self._clean(self._field_value(fields, "ShortDescription"))
            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": self._clean(self._field_value(fields, "Location")),
                    "practice_area": self._clean(self._field_value(fields, "Department")),
                    "pqe_level": self._extract_pqe(title, description),
                    "description": description,
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "lewis_silkin_next_data_allhires",
                        "category": self._clean(self._field_value(fields, "Category")),
                    },
                }
            )
        return jobs

    def _jobs_from_cards(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for card in soup.select('a[href*="lewissilkin.allhires.com/PositionDetail"]'):
            job_url = self._clean(card.get("href"))
            reference = self._reference_from_url(job_url)
            title = self._text(card, '[class*="title"]') or self._first_card_line(card)
            if not reference or not title or not job_url or reference in seen:
                continue

            fields = self._card_fields(card)
            seen.add(reference)
            description = self._text(card, '[class*="desc"]')
            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": fields.get("Location"),
                    "practice_area": fields.get("Department"),
                    "pqe_level": self._extract_pqe(title, description),
                    "description": description,
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "lewis_silkin_html_cards",
                        "category": fields.get("Category"),
                    },
                }
            )
        return jobs

    @classmethod
    def _walk_allhires_fields(cls, value: Any) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        if isinstance(value, dict):
            fields = value.get("fields")
            if isinstance(fields, dict) and "RoleTitle" in fields and "Link" in fields:
                found.append(fields)
            for child in value.values():
                found.extend(cls._walk_allhires_fields(child))
        elif isinstance(value, list):
            for child in value:
                found.extend(cls._walk_allhires_fields(child))
        return found

    @staticmethod
    def _field_value(fields: dict[str, Any], name: str) -> Any:
        value = fields.get(name)
        if isinstance(value, dict):
            return value.get("value")
        return value

    @classmethod
    def _card_fields(cls, card: Any) -> dict[str, str]:
        fields: dict[str, str] = {}
        for row in card.select('[class*="content-line"]'):
            parts = [
                cls._clean(part.get_text(" ", strip=True))
                for part in row.select("p")
                if cls._clean(part.get_text(" ", strip=True))
            ]
            if len(parts) < 2:
                continue
            label = parts[0].rstrip(":")
            fields[label] = parts[1]
        return fields

    @classmethod
    def _first_card_line(cls, card: Any) -> str | None:
        text = cls._clean(card.get_text(" ", strip=True))
        if not text:
            return None
        for marker in (" Category:", " Location:", " Department:"):
            if marker in text:
                return cls._clean(text.split(marker, 1)[0])
        return text

    @classmethod
    def _text(cls, root: Any, selector: str) -> str | None:
        element = root.select_one(selector) if root else None
        if element is None:
            return None
        return cls._clean(element.get_text(" ", strip=True))

    @staticmethod
    def _reference_from_url(url: str | None) -> str | None:
        if not url:
            return None
        value = parse_qs(urlparse(url).query).get("id", [None])[0]
        return str(value).strip() if value else None

    @staticmethod
    def _extract_pqe(title: str, description: str | None) -> str | None:
        text = f"{title} {description or ''}"
        match = re.search(
            r"\b(?:NQ|\d+(?:\s*(?:-|\u2013|to)\s*\d+)?\+?\s*PQE)\b",
            text,
            flags=re.IGNORECASE,
        )
        return " ".join(match.group(0).split()) if match else None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", str(value)).strip()
        return text or None
