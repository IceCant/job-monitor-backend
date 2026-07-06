from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class WombleBondDickinsonPlugin(BasePlugin):
    plugin_name = "womble_bond_dickinson"
    display_name = "Womble Bond Dickinson"
    discoverable = True
    enabled = True
    careers_url = "https://jobs.wbd-uk.com/jobs/vacancy/find/results/"
    description = "Womble Bond Dickinson UK CareerZone scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "max_pages": 0,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = str(self.plugin_config.get("source_url") or self.careers_url)
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
                "X-Requested-With": "XMLHttpRequest",
            }
        )

        response = session.get(source_url, timeout=timeout)
        self._prepare_response(response)
        endpoint = self._grid_endpoint(response.text)
        if not endpoint:
            raise ValueError("Womble Bond Dickinson results endpoint was not found")

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 1
        next_url: str | None = urljoin(response.url, endpoint)

        while next_url:
            if max_pages > 0 and page > max_pages:
                break

            grid_response = session.get(
                next_url,
                params={
                    "pageWidthInput": 1440,
                    "availableWidthInput": 1200,
                    "gadgetsWidthInput": 0,
                    "viewMode": "",
                    "inDialog": "false",
                },
                timeout=timeout,
            )
            self._prepare_response(grid_response)
            soup = BeautifulSoup(grid_response.text, "lxml")
            new_on_page = self._append_jobs(soup, grid_response.url, page, jobs, seen)
            if new_on_page == 0:
                break

            next_url = self._next_page_url(soup, grid_response.url)
            page += 1

        return jobs

    def _append_jobs(
        self,
        soup: BeautifulSoup,
        page_url: str,
        page: int,
        jobs: list[dict[str, Any]],
        seen: set[str],
    ) -> int:
        new_on_page = 0
        for row in soup.select(".ListGridContainer .rowContainer"):
            link = row.select_one(".rowHeader a[href]")
            row_id = row.select_one("input.rowId[value]")
            internal_row_id = self._clean(row_id.get("value") if row_id else None)
            title = self._clean(link.get_text(" ", strip=True) if link else None)
            if not internal_row_id or not title or not link:
                continue

            job_url = urljoin(page_url, str(link.get("href") or ""))
            reference = self._vacancy_reference(job_url) or internal_row_id
            if reference in seen:
                continue
            seen.add(reference)
            new_on_page += 1
            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": self._text(row, ".codelist5value_vacancyColumn"),
                    "practice_area": None,
                    "pqe_level": None,
                    "description": None,
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "wbd_careerzone_html",
                        "internal_row_id": internal_row_id,
                        "contract_type": self._text(row, ".codelist7value_vacancyColumn"),
                        "listing_page": page,
                    },
                }
            )
        return new_on_page

    @staticmethod
    def _grid_endpoint(html: str) -> str | None:
        match = re.search(
            r"['\"]([^'\"]*posbrowser_gridhandler/\?pagestamp=[0-9a-f-]+)['\"]",
            html,
            flags=re.IGNORECASE,
        )
        return match.group(1) if match else None

    @staticmethod
    def _next_page_url(soup: BeautifulSoup, page_url: str) -> str | None:
        link = soup.select_one(".pagingControls_Tiles a.scroller_movenext[href]")
        if link is None:
            return None
        classes = set(link.get("class") or [])
        if link.has_attr("disabled") or "buttonDisabled" in classes:
            return None
        href = str(link.get("href") or "").strip()
        return urljoin(page_url, href) if href else None

    @staticmethod
    def _vacancy_reference(job_url: str) -> str | None:
        parts = [part for part in urlparse(job_url).path.split("/") if part]
        try:
            slug = parts[parts.index("vacancy") + 1]
        except (ValueError, IndexError):
            return None
        for part in reversed(slug.split("-")):
            if part.isdigit():
                return part
        return None

    @classmethod
    def _text(cls, root: Any, selector: str) -> str | None:
        element = root.select_one(selector) if root else None
        return cls._clean(element.get_text(" ", strip=True) if element else None)

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None

    @staticmethod
    def _prepare_response(response: requests.Response) -> None:
        response.raise_for_status()
        response.encoding = "utf-8"
