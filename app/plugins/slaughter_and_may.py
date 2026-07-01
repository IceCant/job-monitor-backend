from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class SlaughterAndMayPlugin(BasePlugin):
    plugin_name = "slaughter_and_may"
    display_name = "Slaughter and May"
    discoverable = True
    enabled = True
    careers_url = "https://careers.slaughterandmay.com/V2/Vacancy"
    description = "Slaughter and May engage|ats careers scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "ajax_url": "https://careers.slaughterandmay.com/V2/Vacancy/ApplySearchFilter",
        "max_pages": 0,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = str(self.plugin_config.get("source_url") or self.careers_url)
        ajax_url = str(self.plugin_config.get("ajax_url") or self.default_config["ajax_url"])
        timeout = int(self.plugin_config.get("timeout", 60))
        max_pages = int(self.plugin_config.get("max_pages", 0))

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                "Referer": source_url,
                "X-Requested-With": "XMLHttpRequest",
            }
        )

        first = session.get(source_url, timeout=timeout)
        first.raise_for_status()
        first.encoding = "utf-8"

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        total_pages = self._page_count(first.text)
        if max_pages > 0:
            total_pages = min(total_pages, max_pages)

        self._append_jobs(first.text, jobs, seen, page=1)

        for page in range(2, total_pages + 1):
            response = session.post(
                ajax_url,
                data={
                    "searchControlViewModel.Criteria": "",
                    "searchControlViewModel.PostCode": "",
                    "searchControlViewModel.TravelDistance": "100",
                    "searchControlViewModel.SortBy": "",
                    "searchControlViewModel.Type": "",
                    "searchControlViewModel.PageNo": str(page),
                },
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            html = data.get("searchResults") or ""
            if not html:
                break
            before = len(jobs)
            self._append_jobs(html, jobs, seen, page=page)
            if len(jobs) == before:
                break

        return jobs

    def _append_jobs(
        self,
        html: str,
        jobs: list[dict[str, Any]],
        seen: set[str],
        page: int,
    ) -> None:
        soup = BeautifulSoup(html, "html.parser")
        for button in soup.select("button.btn-search-results-view"):
            job_url = self._clean(button.get("data-param1"))
            reference = self._reference(job_url) or self._reference(button.get("id"))
            row = button.find_parent("div", class_="row")
            title = self._text(row, ".ats-heading-font") if row else None
            if not job_url or not reference or not title or reference in seen:
                continue

            fields = self._fields(row) if row else {}
            seen.add(reference)
            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": self._location_from_job(job_url, title),
                    "practice_area": fields.get("Vacancy Type"),
                    "pqe_level": None,
                    "description": None,
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "slaughter_and_may_engage_ats",
                        "listing_page": page,
                        "closing_date": fields.get("Closing Date"),
                        "posted": fields.get("Posted"),
                    },
                }
            )

    @staticmethod
    def _page_count(html: str) -> int:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        match = re.search(r"\bPage\s+\d+\s+of\s+(\d+)\b", text, re.IGNORECASE)
        return int(match.group(1)) if match else 1

    @staticmethod
    def _fields(row: Any) -> dict[str, str]:
        fields: dict[str, str] = {}
        for element in row.select(".ats-normal-font, .ats-subheading-font"):
            text = " ".join(element.get_text(" ", strip=True).split())
            if ":" not in text:
                continue
            key, value = text.split(":", 1)
            value = value.strip()
            if value:
                fields[key.strip()] = value
        return fields

    @staticmethod
    def _location_from_job(job_url: str, title: str) -> str:
        text = f"{job_url} {title}".casefold()
        if "brussels" in text or "belgium" in text:
            return "Brussels"
        return "London"

    @staticmethod
    def _reference(value: str | None) -> str | None:
        if not value:
            return None
        parsed = urlparse(value)
        parts = [part for part in parsed.path.split("/") if part]
        for part in parts:
            if part.isdigit() and len(part) >= 5:
                return part
        match = re.search(r"(\d{5,})", value)
        return match.group(1) if match else None

    @staticmethod
    def _text(root: Any, selector: str) -> str | None:
        element = root.select_one(selector) if root else None
        if not element:
            return None
        return " ".join(element.get_text(" ", strip=True).split()) or None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
