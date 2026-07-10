from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from app.plugins.base import BasePlugin


class EarcuPositionBrowserPlugin(BasePlugin):
    """Reusable scraper for Earcu position-browser vacancy grids."""

    plugin_name = "earcu_position_browser"
    display_name = "Earcu Position Browser"
    discoverable = False
    enabled = True
    careers_url = None
    description = "Reusable Earcu position-browser scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": "",
        "max_pages": 0,
        "safety_max_pages": 100,
        "timeout": 60,
    }
    source_name = "earcu_position_browser"
    column_map: dict[str, str] = {}

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = str(self.plugin_config.get("source_url") or self.careers_url or "")
        timeout = int(self.plugin_config.get("timeout", 60))
        max_pages = int(self.plugin_config.get("max_pages", 0))
        safety_max_pages = int(self.plugin_config.get("safety_max_pages", 100))
        if not source_url:
            raise ValueError("Earcu position-browser scraper requires source_url")

        try:
            return self._scrape_with_requests(
                source_url=source_url,
                timeout=timeout,
                max_pages=max_pages,
                safety_max_pages=safety_max_pages,
            )
        except Exception as http_error:
            try:
                return await self._scrape_with_browser(
                    source_url=source_url,
                    timeout=timeout,
                    max_pages=max_pages,
                    safety_max_pages=safety_max_pages,
                )
            except Exception as browser_error:
                raise RuntimeError(
                    f"{self.display_name} HTTP scrape failed ({http_error}); "
                    f"browser fallback also failed ({browser_error})"
                ) from browser_error

    def _scrape_with_requests(
        self,
        *,
        source_url: str,
        timeout: int,
        max_pages: int,
        safety_max_pages: int,
    ) -> list[dict[str, Any]]:
        session = requests.Session()
        session.headers.update(self._headers())

        response = session.get(source_url, timeout=timeout)
        self._prepare_response(response)
        endpoint = self._grid_endpoint(response.text)
        if not endpoint:
            raise ValueError(f"{self.display_name} results endpoint was not found")

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 1
        next_url: str | None = urljoin(response.url, endpoint)

        while next_url:
            if max_pages > 0 and page > max_pages:
                break
            if page > safety_max_pages:
                raise ValueError(
                    f"{self.display_name} pagination exceeded "
                    f"safety_max_pages={safety_max_pages}"
                )

            grid_response = session.get(
                next_url,
                params=self._grid_params(),
                headers={
                    "Accept": "text/html, */*; q=0.01",
                    "Referer": response.url,
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=timeout,
            )
            self._prepare_response(grid_response)
            soup = BeautifulSoup(grid_response.text, "lxml")
            new_on_page = self._append_jobs(soup, grid_response.url, page, jobs, seen)
            if new_on_page == 0:
                if page == 1:
                    raise ValueError(self._empty_response_message(grid_response, soup))
                break

            next_url = self._next_page_url(soup, grid_response.url)
            page += 1

        if not jobs:
            raise ValueError(f"{self.display_name} returned no jobs")
        return jobs

    async def _scrape_with_browser(
        self,
        *,
        source_url: str,
        timeout: int,
        max_pages: int,
        safety_max_pages: int,
    ) -> list[dict[str, Any]]:
        timeout_ms = timeout * 1000
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage"],
            )
            try:
                context = await browser.new_context(
                    user_agent=self._headers()["User-Agent"],
                    viewport={"width": 1440, "height": 1000},
                    locale="en-GB",
                )
                page = await context.new_page()
                page.set_default_timeout(timeout_ms)
                await page.goto(source_url, wait_until="domcontentloaded", timeout=timeout_ms)
                rows_ready = await self._wait_for_browser_rows(
                    page,
                    timeout_ms=min(timeout_ms, 10_000),
                )
                if not rows_ready:
                    endpoint = self._grid_endpoint(await page.content())
                    if not endpoint:
                        raise ValueError(
                            f"{self.display_name} grid endpoint disappeared in browser"
                        )
                    await page.goto(
                        self._browser_grid_url(page.url, endpoint),
                        wait_until="domcontentloaded",
                        timeout=timeout_ms,
                    )
                    rows_ready = await self._wait_for_browser_rows(
                        page,
                        timeout_ms=timeout_ms,
                    )
                if not rows_ready:
                    raise ValueError(await self._browser_empty_message(page))

                for page_number in range(1, safety_max_pages + 1):
                    soup = BeautifulSoup(await page.content(), "lxml")
                    new_on_page = self._append_jobs(
                        soup,
                        page.url,
                        page_number,
                        jobs,
                        seen,
                    )
                    if new_on_page == 0:
                        raise ValueError(
                            f"{self.display_name} browser returned no rows "
                            f"on page {page_number}"
                        )

                    if max_pages > 0 and page_number >= max_pages:
                        break

                    next_url = self._next_page_url(soup, page.url)
                    if not next_url:
                        break

                    await page.goto(next_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    if not await self._wait_for_browser_rows(page, timeout_ms=timeout_ms):
                        raise ValueError(await self._browser_empty_message(page))
                else:
                    raise ValueError(
                        f"{self.display_name} browser pagination exceeded "
                        f"safety_max_pages={safety_max_pages}"
                    )
            finally:
                await browser.close()

        if not jobs:
            raise ValueError(f"{self.display_name} browser fallback returned no jobs")
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

            fields = {
                key: self._column_text(row, column)
                for key, column in self.column_map.items()
            }
            seen.add(reference)
            new_on_page += 1
            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": fields.get("office_location"),
                    "practice_area": fields.get("practice_area"),
                    "pqe_level": self._extract_pqe(title),
                    "description": None,
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": self.source_name,
                        "internal_row_id": internal_row_id,
                        "listing_page": page,
                        **{
                            key: value
                            for key, value in fields.items()
                            if key not in {"office_location", "practice_area"}
                            and value
                        },
                    },
                }
            )
        return new_on_page

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/137.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
            "Cache-Control": "no-cache",
        }

    @staticmethod
    def _grid_params() -> dict[str, Any]:
        return {
            "pageWidthInput": 1440,
            "availableWidthInput": 1200,
            "gadgetsWidthInput": 0,
            "viewMode": "",
            "inDialog": "false",
        }

    @staticmethod
    def _browser_grid_url(page_url: str, endpoint: str) -> str:
        params = urlencode(EarcuPositionBrowserPlugin._grid_params())
        separator = "&" if "?" in endpoint else "?"
        return urljoin(page_url, f"{endpoint}{separator}{params}")

    @staticmethod
    async def _wait_for_browser_rows(page: Any, timeout_ms: int) -> bool:
        try:
            await page.locator(".ListGridContainer .rowContainer").first.wait_for(
                state="attached",
                timeout=timeout_ms,
            )
            return True
        except PlaywrightTimeoutError:
            return False

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
    def _column_text(cls, root: Any, column: str | None) -> str | None:
        if not column:
            return None
        return cls._text(root, f".{column}_vacancyColumn")

    @classmethod
    def _text(cls, root: Any, selector: str) -> str | None:
        element = root.select_one(selector) if root else None
        return cls._clean(element.get_text(" ", strip=True) if element else None)

    @staticmethod
    def _extract_pqe(title: str | None) -> str | None:
        match = re.search(
            r"\b(?:NQ|\d+(?:\s*(?:-|\u2013|to)\s*\d+)?\+?\s*PQE)\b",
            title or "",
            flags=re.IGNORECASE,
        )
        return " ".join(match.group(0).split()) if match else None

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

    @classmethod
    def _empty_response_message(
        cls,
        response: requests.Response,
        soup: BeautifulSoup,
    ) -> str:
        title = cls._clean(soup.title.get_text(" ", strip=True) if soup.title else None)
        body_text = cls._clean(soup.get_text(" ", strip=True)) or ""
        return (
            "Earcu results endpoint returned no job rows "
            f"(status={response.status_code}, bytes={len(response.content)}, "
            f"url={response.url}, title={title or 'none'}, "
            f"preview={body_text[:180] or 'empty'})"
        )

    @classmethod
    async def _browser_empty_message(cls, page: Any) -> str:
        content = BeautifulSoup(await page.content(), "lxml")
        body_text = cls._clean(content.get_text(" ", strip=True)) or ""
        return f"Earcu browser did not receive job rows (url={page.url}, preview={body_text[:220]})"
