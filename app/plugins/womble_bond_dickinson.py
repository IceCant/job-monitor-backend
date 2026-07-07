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


class WombleBondDickinsonScrapeError(RuntimeError):
    pass


class WombleBondDickinsonPlugin(BasePlugin):
    diagnostic_version = "2026-07-07.4"
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
        "safety_max_pages": 100,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = str(self.plugin_config.get("source_url") or self.careers_url)
        timeout = int(self.plugin_config.get("timeout", 60))
        max_pages = int(self.plugin_config.get("max_pages", 0))
        safety_max_pages = int(self.plugin_config.get("safety_max_pages", 100))
        self._report(
            f"starting; source={source_url}; timeout={timeout}s",
            percent=10,
            stage="Connecting",
        )

        http_error: Exception | None = None
        try:
            return self._scrape_with_requests(
                source_url=source_url,
                timeout=timeout,
                max_pages=max_pages,
                safety_max_pages=safety_max_pages,
            )
        except Exception as exc:  # WBD sometimes blocks cloud HTTP clients.
            http_error = exc
            self._report(
                f"HTTP path failed: {exc}; starting Chromium fallback",
                percent=35,
                stage="Browser fallback",
            )

        try:
            return await self._scrape_with_browser(
                source_url=source_url,
                timeout=timeout,
                max_pages=max_pages,
                safety_max_pages=safety_max_pages,
            )
        except Exception as browser_error:
            self._report(
                f"Chromium fallback failed: {browser_error}",
                percent=70,
                stage="Failed",
            )
            raise WombleBondDickinsonScrapeError(
                "WBD HTTP scrape failed "
                f"({http_error}); browser fallback also failed ({browser_error})"
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
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),
                "Accept-Language": "en-GB,en;q=0.9",
                "Cache-Control": "no-cache",
            }
        )

        response = session.get(source_url, timeout=timeout)
        self._report_response("HTTP landing page", response, percent=15)
        self._prepare_response(response)
        endpoint = self._grid_endpoint(response.text)
        if not endpoint:
            raise ValueError("Womble Bond Dickinson results endpoint was not found")
        self._report(
            "temporary grid endpoint detected",
            percent=20,
            stage="Loading results",
        )

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 1
        next_url: str | None = urljoin(response.url, endpoint)

        while next_url:
            if max_pages > 0 and page > max_pages:
                break
            if page > safety_max_pages:
                raise WombleBondDickinsonScrapeError(
                    f"WBD pagination exceeded safety_max_pages={safety_max_pages}"
                )

            grid_response = session.get(
                next_url,
                params={
                    "pageWidthInput": 1440,
                    "availableWidthInput": 1200,
                    "gadgetsWidthInput": 0,
                    "viewMode": "",
                    "inDialog": "false",
                },
                headers={
                    "Accept": "text/html, */*; q=0.01",
                    "Referer": response.url,
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=timeout,
            )
            self._report_response(
                f"HTTP grid page {page}",
                grid_response,
                percent=min(30 + page * 5, 65),
            )
            self._prepare_response(grid_response)
            soup = BeautifulSoup(grid_response.text, "lxml")
            raw_rows = len(soup.select(".ListGridContainer .rowContainer"))
            new_on_page = self._append_jobs(soup, grid_response.url, page, jobs, seen)
            self._report(
                f"HTTP grid page {page}: rows={raw_rows}, "
                f"new={new_on_page}, total={len(jobs)}",
                percent=min(35 + page * 5, 70),
                stage="Parsing results",
                jobs_seen=len(jobs),
            )
            if new_on_page == 0:
                if page == 1:
                    raise WombleBondDickinsonScrapeError(
                        self._empty_response_message(grid_response, soup)
                    )
                break

            next_url = self._next_page_url(soup, grid_response.url)
            page += 1

        if not jobs:
            raise WombleBondDickinsonScrapeError(
                "WBD returned no jobs from its results endpoint"
            )
        self._report(
            f"HTTP path complete: jobs={len(jobs)}",
            percent=70,
            stage="Results ready",
            jobs_seen=len(jobs),
        )
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
        self._report(
            "launching headless Chromium",
            percent=40,
            stage="Browser fallback",
        )

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage"],
            )
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/137.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1440, "height": 1000},
                    locale="en-GB",
                )
                page = await context.new_page()
                page.set_default_timeout(timeout_ms)
                navigation = await page.goto(
                    source_url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
                self._report(
                    "Chromium landing page: "
                    f"status={navigation.status if navigation else 'unknown'}, "
                    f"url={page.url}",
                    percent=45,
                    stage="Browser fallback",
                )
                rows_ready = await self._wait_for_browser_rows(
                    page,
                    timeout_ms=min(timeout_ms, 10_000),
                )
                if not rows_ready:
                    # AWS WAF returned its challenge inside an XHR. Opening the
                    # same temporary endpoint as a document lets its JavaScript
                    # run and obtain the normal aws-waf-token session cookie.
                    landing_html = await page.content()
                    endpoint = self._grid_endpoint(landing_html)
                    if not endpoint:
                        raise WombleBondDickinsonScrapeError(
                            "WBD grid endpoint disappeared before browser retry"
                        )
                    grid_url = self._browser_grid_url(page.url, endpoint)
                    self._report(
                        "job rows did not load through AJAX; opening the grid "
                        "as a top-level page for the AWS WAF challenge",
                        percent=48,
                        stage="AWS verification",
                    )
                    grid_navigation = await page.goto(
                        grid_url,
                        wait_until="domcontentloaded",
                        timeout=timeout_ms,
                    )
                    self._report(
                        "Chromium grid navigation: "
                        f"status={grid_navigation.status if grid_navigation else 'unknown'}, "
                        f"url={page.url}",
                        percent=50,
                        stage="AWS verification",
                    )
                    rows_ready = await self._wait_for_browser_rows(
                        page,
                        timeout_ms=timeout_ms,
                    )
                if not rows_ready:
                    raise WombleBondDickinsonScrapeError(
                        await self._browser_challenge_message(page)
                    )

                for page_number in range(1, safety_max_pages + 1):
                    html = await page.content()
                    soup = BeautifulSoup(html, "lxml")
                    raw_rows = len(
                        soup.select(".ListGridContainer .rowContainer")
                    )
                    new_on_page = self._append_jobs(
                        soup,
                        page.url,
                        page_number,
                        jobs,
                        seen,
                    )
                    self._report(
                        f"Chromium page {page_number}: rows={raw_rows}, "
                        f"new={new_on_page}, total={len(jobs)}",
                        percent=min(45 + page_number * 5, 70),
                        stage="Browser parsing",
                        jobs_seen=len(jobs),
                    )
                    if new_on_page == 0:
                        raise WombleBondDickinsonScrapeError(
                            f"WBD browser returned no new rows on page {page_number}"
                        )

                    if max_pages > 0 and page_number >= max_pages:
                        break

                    next_link = page.locator(
                        ".pagingControls_Tiles a.scroller_movenext[href]"
                    ).first
                    if await next_link.count() == 0:
                        break
                    classes = set(
                        (await next_link.get_attribute("class") or "").split()
                    )
                    is_disabled = (
                        await next_link.get_attribute("disabled") is not None
                        or "buttonDisabled" in classes
                    )
                    if is_disabled:
                        break

                    next_href = await next_link.get_attribute("href")
                    if not next_href:
                        break
                    next_url = urljoin(page.url, next_href)
                    next_navigation = await page.goto(
                        next_url,
                        wait_until="domcontentloaded",
                        timeout=timeout_ms,
                    )
                    self._report(
                        f"Chromium page {page_number + 1} navigation: "
                        f"status={next_navigation.status if next_navigation else 'unknown'}, "
                        f"url={page.url}",
                        percent=min(50 + page_number * 5, 70),
                        stage="Browser pagination",
                        jobs_seen=len(jobs),
                    )
                    if not await self._wait_for_browser_rows(
                        page,
                        timeout_ms=timeout_ms,
                    ):
                        raise WombleBondDickinsonScrapeError(
                            await self._browser_challenge_message(page)
                        )
                else:
                    raise WombleBondDickinsonScrapeError(
                        f"WBD browser pagination exceeded safety_max_pages={safety_max_pages}"
                    )
            finally:
                await browser.close()

        if not jobs:
            raise WombleBondDickinsonScrapeError("WBD browser fallback returned no jobs")
        self._report(
            f"Chromium path complete: jobs={len(jobs)}",
            percent=70,
            stage="Results ready",
            jobs_seen=len(jobs),
        )
        return jobs

    @staticmethod
    async def _wait_for_browser_rows(page: Any, timeout_ms: int) -> bool:
        try:
            await page.locator(
                ".ListGridContainer .rowContainer"
            ).first.wait_for(
                state="attached",
                timeout=timeout_ms,
            )
            return True
        except PlaywrightTimeoutError:
            return False

    @staticmethod
    def _browser_grid_url(page_url: str, endpoint: str) -> str:
        params = urlencode(
            {
                "pageWidthInput": 1440,
                "availableWidthInput": 1200,
                "gadgetsWidthInput": 0,
                "viewMode": "",
                "inDialog": "false",
            }
        )
        separator = "&" if "?" in endpoint else "?"
        return urljoin(page_url, f"{endpoint}{separator}{params}")

    @classmethod
    async def _browser_challenge_message(cls, page: Any) -> str:
        cookies = await page.context.cookies()
        cookie_names = sorted(
            str(cookie.get("name"))
            for cookie in cookies
            if cookie.get("name")
        )
        content = BeautifulSoup(await page.content(), "lxml")
        body_text = cls._clean(content.get_text(" ", strip=True)) or ""
        return (
            "WBD browser did not receive job rows after AWS verification "
            f"(url={page.url}, cookies={cookie_names}, "
            f"preview={body_text[:220] or 'empty'})"
        )

    def _report(
        self,
        message: str,
        *,
        percent: int,
        stage: str,
        jobs_seen: int = 0,
    ) -> None:
        line = f"[WBD {self.diagnostic_version}] {message}"
        print(line, flush=True)
        callback = self.kwargs.get("progress_callback")
        if callable(callback):
            callback(
                {
                    "current_firm_percent": percent,
                    "current_firm_stage": stage,
                    "message": line,
                    "jobs_seen": jobs_seen,
                    "logs": [line],
                }
            )

    def _report_response(
        self,
        label: str,
        response: requests.Response,
        *,
        percent: int,
    ) -> None:
        self._report(
            f"{label}: status={response.status_code}, "
            f"bytes={len(response.content)}, url={response.url}, "
            f"cloudfront_pop={response.headers.get('x-amz-cf-pop') or 'unknown'}",
            percent=percent,
            stage="Loading results",
        )

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

    @classmethod
    def _empty_response_message(
        cls,
        response: requests.Response,
        soup: BeautifulSoup,
    ) -> str:
        title = cls._clean(soup.title.get_text(" ", strip=True) if soup.title else None)
        body_text = cls._clean(soup.get_text(" ", strip=True)) or ""
        preview = body_text[:180]
        cloudfront_pop = response.headers.get("x-amz-cf-pop") or "unknown"
        return (
            "WBD results endpoint returned no job rows "
            f"(status={response.status_code}, bytes={len(response.content)}, "
            f"url={response.url}, cloudfront_pop={cloudfront_pop}, "
            f"title={title or 'none'}, preview={preview or 'empty'})"
        )
