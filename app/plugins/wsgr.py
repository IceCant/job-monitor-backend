import html
import re
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class WSGRPlugin(BasePlugin):
    plugin_name = "wsgr"
    display_name = "Wilson Sonsini"
    enabled = True
    careers_url = "https://careers.wsgr.com/openings/"
    description = "Wilson Sonsini openings scraper"
    required_config = ["source_url"]
    api_url = "https://careers.wsgr.com/wp-json/wp/v2/opening?per_page=100&_embed=wp:term"
    default_config = {
        "source_url": careers_url,
        "api_url": api_url,
        "max_listing_pages": 15,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = self.plugin_config.get("source_url") or self.careers_url
        api_url = self.plugin_config.get("api_url") or self.api_url
        max_listing_pages = int(self.plugin_config.get("max_listing_pages") or 15)
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

        listing_meta = self._listing_meta(session, source_url, max_listing_pages)
        response = session.get(api_url, timeout=60)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            return []

        return [
            self._job_from_post(post, listing_meta)
            for post in data
            if isinstance(post, dict)
        ]

    def _listing_meta(
        self,
        session: requests.Session,
        source_url: str,
        max_pages: int,
    ) -> dict[str, dict[str, str | None]]:
        meta: dict[str, dict[str, str | None]] = {}
        total_pages = max_pages
        page_no = 1
        while page_no <= total_pages:
            page_url = source_url if page_no == 1 else f"{source_url.rstrip('/')}/?_paged={page_no}"
            try:
                response = session.get(page_url, timeout=60)
                response.raise_for_status()
                response.encoding = "utf-8"
            except requests.RequestException:
                break

            page_meta = self._parse_listing_meta(response.text, page_url)
            if not page_meta:
                break
            meta.update(page_meta)

            detected_total = self._total_listing_pages(response.text)
            if detected_total:
                total_pages = min(max_pages, detected_total)
            page_no += 1
        return meta

    def _parse_listing_meta(self, html_text: str, page_url: str) -> dict[str, dict[str, str | None]]:
        soup = BeautifulSoup(html_text, "html.parser")
        listing_meta: dict[str, dict[str, str | None]] = {}
        for card in soup.select(".facetwp-template .box"):
            title_el = card.select_one(".box__title a")
            if title_el is None:
                continue
            job_url = urljoin(page_url, title_el.get("href") or "")
            slug = self._slug_from_url(job_url)
            meta = self._meta(card)
            apply_url = self._apply_url(card, page_url)
            listing_meta[slug] = {
                "office_location": meta.get("Office"),
                "practice_area": meta.get("Practice") or meta.get("Department"),
                "excerpt": self._text(card.select_one(".box__content > p")),
                "apply_url": apply_url,
            }
        return listing_meta

    def _job_from_post(
        self,
        post: dict[str, Any],
        listing_meta: dict[str, dict[str, str | None]],
    ) -> dict[str, Any]:
        title = self._rendered(post.get("title"))
        description = self._html_to_text(self._rendered(post.get("content")))
        excerpt = self._html_to_text(self._rendered(post.get("excerpt")))
        job_url = str(post.get("link") or "").strip()
        reference = str(post.get("id") or post.get("slug") or job_url).strip()
        terms = self._terms(post)
        slug = str(post.get("slug") or self._slug_from_url(job_url))
        listed = listing_meta.get(slug, {})
        office_location, locations = self._office_location(
            listed.get("office_location"),
            description or excerpt or "",
        )

        return {
            "job_url": job_url,
            "firm_name": self.firm_name,
            "title": title,
            "office_location": office_location,
            "practice_area": listed.get("practice_area") or terms.get("department"),
            "pqe_level": None,
            "description": description or listed.get("excerpt") or excerpt,
            "source_reference": reference,
            "status": "LIVE",
            "extra_info": {
                "source": "wsgr_wordpress_rest",
                "post_id": post.get("id"),
                "slug": slug,
                "apply_url": listed.get("apply_url"),
                "contract_type": terms.get("contract_type"),
                "date": post.get("date"),
                "modified": post.get("modified"),
                "locations": locations,
            },
        }

    @staticmethod
    def _terms(post: dict[str, Any]) -> dict[str, str]:
        grouped: dict[str, list[str]] = {}
        embedded_terms = (post.get("_embedded") or {}).get("wp:term") or []
        for term_group in embedded_terms:
            if not isinstance(term_group, list):
                continue
            for term in term_group:
                if not isinstance(term, dict):
                    continue
                taxonomy = term.get("taxonomy")
                name = term.get("name")
                if taxonomy and name:
                    grouped.setdefault(str(taxonomy), []).append(str(name))
        return {key: ", ".join(values) for key, values in grouped.items()}

    @staticmethod
    def _meta(card: BeautifulSoup) -> dict[str, str]:
        meta: dict[str, str] = {}
        for item in card.select(".meta__item"):
            label = item.select_one("dt")
            values = [dd.get_text(" ", strip=True) for dd in item.select("dd")]
            key = label.get_text(" ", strip=True).rstrip(":") if label else None
            if key and values:
                meta[key] = ", ".join(value for value in values if value)
        return meta

    @staticmethod
    def _apply_url(card: BeautifulSoup, page_url: str) -> str | None:
        for link in card.select("a[href]"):
            if link.get_text(" ", strip=True).lower() == "apply":
                return urljoin(page_url, link["href"])
        return None

    @staticmethod
    def _slug_from_url(job_url: str) -> str:
        return job_url.rstrip("/").rsplit("/", 1)[-1]

    @staticmethod
    def _total_listing_pages(html_text: str) -> int | None:
        match = re.search(r'"total_pages"\s*:\s*(\d+)', html_text)
        if not match:
            return None
        return int(match.group(1))

    @staticmethod
    def _rendered(value: Any) -> str | None:
        if isinstance(value, dict):
            value = value.get("rendered")
        if value is None:
            return None
        text = html.unescape(str(value)).strip()
        return text or None

    @staticmethod
    def _location_from_text(text: str) -> str | None:
        patterns = [
            r"primary location for this job posting is in ([^.]+)",
            r"position is based in ([^.]+)",
            r"sit in our ([^.]+?) office",
            r"join our firm in our ([^.]+?) office",
            r"part of the downtown ([^.]+?) office",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    @classmethod
    def _office_location(cls, listed_location: str | None, text: str) -> tuple[str | None, list[str]]:
        listed = cls._clean_location(listed_location)
        if listed and listed.casefold() != "multiple locations":
            locations = cls._split_locations(listed)
            if len(locations) > 1:
                return "; ".join(locations), locations
            return listed, locations

        locations = cls._locations_from_text(text)
        if locations:
            return "; ".join(locations), locations

        fallback = cls._location_from_text(text)
        if fallback:
            locations = cls._split_locations(fallback)
            return "; ".join(locations), locations

        if listed and listed.casefold() == "multiple locations":
            return "Multiple WSGR offices", ["Multiple WSGR offices"]
        return listed or "Location not specified", cls._split_locations(listed)

    @classmethod
    def _locations_from_text(cls, text: str) -> list[str]:
        normalized = cls._clean_location(text) or ""
        if not normalized:
            return []

        location_sets: list[list[str]] = []

        for pattern in [
            r"preferred locations? (?:are|include)\s+(.+?)(?:Compensation and Benefits|Salary range|Discretionary merit|$)",
            r"(?:team|group) is located in our\s+(.+?)\s+offices?",
            r"you may sit in\s+(.+?)(?:\.|;)",
            r"would welcome attorneys who want to join the team in those locations",
        ]:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                if match.lastindex:
                    location_sets.append(cls._split_locations(match.group(1)))
                else:
                    window = normalized[max(0, match.start() - 180): match.start()]
                    location_sets.append(cls._split_locations(window))

        primary_match = re.search(
            r"primary location for this job posting is in ([^.]+?)(?:, but other locations may be listed)?\.",
            normalized,
            flags=re.IGNORECASE,
        )
        primary = cls._split_locations(primary_match.group(1)) if primary_match else []

        pay_section = ""
        pay_match = re.search(
            r"anticipated pay range for this position is as follows:\s+(.+?)(?:The compensation|Benefits information|Equal Opportunity|$)",
            normalized,
            flags=re.IGNORECASE,
        )
        if pay_match:
            pay_section = pay_match.group(1)

        pay_locations = cls._locations_from_pay_ranges(pay_section)
        if primary and pay_locations:
            return cls._dedupe_locations(primary + pay_locations)
        if pay_locations:
            return pay_locations
        for values in location_sets:
            if values:
                return values
        return primary

    @classmethod
    def _locations_from_pay_ranges(cls, text: str) -> list[str]:
        if not text:
            return []
        locations: list[str] = []
        for chunk in re.finditer(r"([^:.]+):\s*\$[\d,]+", text):
            before_colon = chunk.group(1)
            segment = re.split(r"(?:per year|per hour)\.?", before_colon)[-1]
            locations.extend(cls._split_locations(segment))
        return cls._dedupe_locations(locations)

    @classmethod
    def _split_locations(cls, value: str | None) -> list[str]:
        cleaned = cls._clean_location(value)
        if not cleaned:
            return []

        cleaned = re.sub(r"\ball other locations\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bother locations\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\band all\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bWashington\s*,?\s*D\.?C\.?(?=[\s,.;]|$)", "Washington__DC__", cleaned)
        cleaned = re.sub(r"\bDC\b", "Washington__DC__", cleaned)
        cleaned = re.sub(r"\bSalt Lake(?! City\b)", "Salt Lake City", cleaned)
        cleaned = re.sub(r"\s+or\s+", ", ", cleaned)
        cleaned = cleaned.replace(" and ", ", ")
        pieces = [
            part.strip(" ,;.")
            for part in re.split(r"\s*,\s*|\s*;\s*", cleaned)
            if part.strip(" ,;.")
        ]

        locations: list[str] = []
        index = 0
        while index < len(pieces):
            part = pieces[index]
            if part.casefold() == "and":
                index += 1
                continue
            if part == "Washington__DC__":
                locations.append("Washington, D.C.")
                index += 1
                continue
            locations.append(part.replace("Washington__DC__", "Washington, D.C."))
            index += 1

        return cls._dedupe_locations(locations)

    @staticmethod
    def _dedupe_locations(locations: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for location in locations:
            normalized = " ".join(location.split()).strip(" ,;")
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
        return deduped

    @staticmethod
    def _clean_location(value: str | None) -> str | None:
        if not value:
            return None
        text = " ".join(str(value).replace("\xa0", " ").split())
        return text.strip(" ,;") or None

    @staticmethod
    def _html_to_text(html_text: str | None) -> str | None:
        if not html_text:
            return None
        soup = BeautifulSoup(html_text, "html.parser")
        for element in soup.select("script, style"):
            element.decompose()
        lines = [line.strip() for line in soup.get_text("\n", strip=True).splitlines() if line.strip()]
        return "\n".join(lines) or None

    @staticmethod
    def _text(element: Any) -> str | None:
        if element is None:
            return None
        text = " ".join(element.get_text(" ", strip=True).split())
        return text or None
