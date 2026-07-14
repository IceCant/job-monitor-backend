from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class PenningtonsLawPlugin(BasePlugin):
    plugin_name = "penningtons_law"
    display_name = "Penningtons Manches Cooper"
    enabled = True
    careers_url = "http://careers-penningtonslaw.icims.com/jobs/search?ss=1"
    description = "Penningtons Manches Cooper iCIMS careers scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": "https://careers-penningtonslaw.icims.com/jobs/search?ss=1&in_iframe=1",
        "fetch_detail_pages": True,
        "max_pages": 0,
        "timeout": 30,
        "detail_timeout": 10,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = self._iframe_url(str(self.plugin_config.get("source_url") or self.careers_url))
        timeout = int(self.plugin_config.get("timeout", 30))
        detail_timeout = int(self.plugin_config.get("detail_timeout", 10))
        fetch_detail_pages = bool(self.plugin_config.get("fetch_detail_pages", True))
        max_pages = int(self.plugin_config.get("max_pages", 0))

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
        self._prepare_response(response)

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 1

        while True:
            soup = BeautifulSoup(response.text, "lxml")
            before = len(jobs)
            self._append_jobs(
                soup,
                session,
                detail_timeout,
                fetch_detail_pages,
                page,
                jobs,
                seen,
            )
            if len(jobs) == before:
                break
            if max_pages > 0 and page >= max_pages:
                break

            next_url = self._next_page_url(soup, response.url)
            if not next_url:
                break
            response = session.get(next_url, timeout=timeout)
            self._prepare_response(response)
            page += 1

        if not jobs:
            raise ValueError("Penningtons iCIMS careers page returned no jobs")
        return jobs

    def _append_jobs(
        self,
        soup: BeautifulSoup,
        session: requests.Session,
        detail_timeout: int,
        fetch_detail_pages: bool,
        page: int,
        jobs: list[dict[str, Any]],
        seen: set[str],
    ) -> None:
        for card in soup.select(".iCIMS_JobCardItem"):
            link = card.select_one("a.iCIMS_Anchor[href]")
            if link is None:
                continue

            title = self._text(link, "h3") or self._clean(link.get_text(" ", strip=True))
            detail_url = self._iframe_url(str(link.get("href") or ""))
            job_url = self._public_url(detail_url)
            fields = self._listing_fields(card)
            reference = fields.get("ID") or self._reference_from_url(detail_url)
            if not title or not detail_url or not reference or reference in seen:
                continue

            listing_description = self._text(card, ".description")
            detail = self._fetch_detail(session, detail_url, detail_timeout) if fetch_detail_pages else {}
            seen.add(reference)
            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": detail.get("title") or title,
                    "office_location": detail.get("location") or fields.get("Job Locations"),
                    "practice_area": detail.get("category"),
                    "pqe_level": self._extract_pqe(title, detail.get("description") or listing_description),
                    "description": detail.get("description") or listing_description,
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "penningtons_icims_html",
                        "listing_page": page,
                        "raw_location": detail.get("raw_location") or fields.get("raw_location"),
                        "posted_date": detail.get("posted_date"),
                        "job_id": detail.get("job_id") or fields.get("ID"),
                        "openings": detail.get("openings"),
                        "description_source": "detail_page" if detail.get("description") else "listing_row",
                    },
                }
            )

    def _fetch_detail(self, session: requests.Session, detail_url: str, timeout: int) -> dict[str, str | None]:
        try:
            response = session.get(detail_url, timeout=timeout)
            self._prepare_response(response)
        except requests.RequestException:
            return {}

        soup = BeautifulSoup(response.text, "lxml")
        content = soup.select_one(".iCIMS_JobContent") or soup
        fields = self._detail_header_fields(content)
        raw_location = fields.get("Job Locations")
        return {
            "title": self._text(content, "h1.iCIMS_Header"),
            "location": self._format_locations(raw_location),
            "raw_location": raw_location,
            "posted_date": fields.get("Posted Date"),
            "job_id": fields.get("Job ID"),
            "openings": fields.get("# of Openings"),
            "category": fields.get("Category"),
            "description": self._detail_description(content),
        }

    @classmethod
    def _listing_fields(cls, card: Any) -> dict[str, str]:
        fields: dict[str, str] = {}
        raw_location = cls._text(card, ".header.left")
        if raw_location:
            raw_location = re.sub(r"^Job Locations\s+", "", raw_location, flags=re.IGNORECASE)
            fields["raw_location"] = raw_location
            formatted = cls._format_locations(raw_location)
            if formatted:
                fields["Job Locations"] = formatted

        for item in card.select(".iCIMS_JobHeaderTag"):
            label = cls._text(item, ".iCIMS_JobHeaderField")
            value = cls._text(item, ".iCIMS_JobHeaderData")
            if label and value:
                fields[label] = value
        return fields

    @classmethod
    def _detail_header_fields(cls, content: Any) -> dict[str, str]:
        fields: dict[str, str] = {}
        raw_location = cls._text(content, ".header.left")
        if raw_location:
            fields["Job Locations"] = re.sub(
                r"^Job Locations\s+",
                "",
                raw_location,
                flags=re.IGNORECASE,
            )

        posted = content.select_one(".header.right span[title]")
        if posted is not None:
            value = cls._clean(posted.get("title")) or cls._clean(posted.get_text(" ", strip=True))
            if value:
                fields["Posted Date"] = value

        for item in content.select(".iCIMS_JobHeaderTag"):
            label = cls._text(item, ".iCIMS_JobHeaderField")
            value = cls._text(item, ".iCIMS_JobHeaderData")
            if label and value:
                fields[label] = value
        return fields

    @classmethod
    def _detail_description(cls, content: Any) -> str | None:
        sections: list[str] = []
        for heading in content.select("h2.iCIMS_InfoField_Job"):
            label = cls._clean(heading.get_text(" ", strip=True))
            body = heading.find_next_sibling("div")
            text = cls._clean_multiline(body.get_text("\n", strip=True) if body else None)
            if label and text:
                sections.append(f"{label}\n{text}")
        return "\n\n".join(sections) or None

    @classmethod
    def _next_page_url(cls, soup: BeautifulSoup, current_url: str) -> str | None:
        for link in soup.select("a[href]"):
            text = cls._clean(link.get_text(" ", strip=True)) or ""
            href = str(link.get("href") or "")
            if "next" in text.casefold() or "pr=" in href:
                return cls._iframe_url(urljoin(current_url, href))
        return None

    @classmethod
    def _iframe_url(cls, url: str) -> str:
        parsed = urlparse(urljoin("https://careers-penningtonslaw.icims.com", url.strip()))
        scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "https"
        if scheme == "http":
            scheme = "https"
        query = parse_qs(parsed.query, keep_blank_values=True)
        query["in_iframe"] = ["1"]
        return urlunparse(
            parsed._replace(
                scheme=scheme,
                query=urlencode(query, doseq=True),
            )
        )

    @staticmethod
    def _public_url(detail_url: str) -> str:
        parsed = urlparse(detail_url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        query.pop("in_iframe", None)
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    @classmethod
    def _format_locations(cls, value: str | None) -> str | None:
        if not value:
            return None
        locations: list[str] = []
        seen: set[str] = set()
        for raw_part in re.split(r"\s*\|\s*", value):
            part = cls._clean(raw_part)
            if not part:
                continue
            formatted = cls._format_location(part)
            key = formatted.casefold()
            if key not in seen:
                seen.add(key)
                locations.append(formatted)
        return "; ".join(locations) or None

    @staticmethod
    def _format_location(value: str) -> str:
        parts = [part for part in value.split("-") if part]
        if len(parts) >= 2 and parts[0].upper() == "UK":
            return f"{parts[-1]}, UK"
        if len(parts) >= 2:
            return ", ".join(reversed(parts))
        return value

    @staticmethod
    def _reference_from_url(url: str) -> str | None:
        parts = [part for part in urlparse(url).path.split("/") if part]
        if "jobs" in parts:
            index = parts.index("jobs")
            if index + 1 < len(parts):
                return parts[index + 1]
        return None

    @classmethod
    def _text(cls, root: Any, selector: str) -> str | None:
        element = root.select_one(selector) if root else None
        if element is None:
            return None
        return cls._clean(element.get_text(" ", strip=True))

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
        text = " ".join(str(value).replace("\xa0", " ").split())
        return text or None

    @staticmethod
    def _clean_multiline(value: str | None) -> str | None:
        if not value:
            return None
        lines = [" ".join(line.replace("\xa0", " ").split()) for line in value.splitlines()]
        text = "\n".join(line for line in lines if line)
        return text or None

    @staticmethod
    def _prepare_response(response: requests.Response) -> None:
        response.raise_for_status()
        response.encoding = "utf-8"
