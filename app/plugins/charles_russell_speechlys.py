from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from app.plugins.base import BasePlugin
from app.plugins.helper.helper import html_to_text


class CharlesRussellSpeechlysPlugin(BasePlugin):
    diagnostic_version = "2026-07-10.1"
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

        http_error: Exception | None = None
        try:
            return self._scrape_with_requests(
                source_url=source_url,
                fetch_detail_pages=fetch_detail_pages,
                max_pages=max_pages,
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - cloud hosts may be blocked by WAF rules.
            http_error = exc
            self._report(
                f"HTTP path failed: {self._error_summary(exc)}; starting Chromium fallback",
                percent=35,
                stage="Browser fallback",
            )

        try:
            return await self._scrape_with_browser(
                source_url=source_url,
                fetch_detail_pages=fetch_detail_pages,
                max_pages=max_pages,
                timeout=timeout,
            )
        except Exception as browser_error:
            self._report(
                f"Chromium fallback failed: {browser_error}",
                percent=75,
                stage="Failed",
            )
            raise ValueError(
                "Charles Russell Speechlys HTTP scrape failed "
                f"({self._error_summary(http_error)}); browser fallback also failed "
                f"({browser_error})"
            ) from browser_error

    def _scrape_with_requests(
        self,
        *,
        source_url: str,
        fetch_detail_pages: bool,
        max_pages: int,
        timeout: int,
    ) -> list[dict[str, Any]]:
        session = requests.Session()
        session.headers.update(self._request_headers())

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 1
        total_pages = 1

        while page <= total_pages:
            if max_pages > 0 and page > max_pages:
                break
            page_url = self._page_url(source_url, page)
            response = session.get(page_url, timeout=timeout)
            self._report_response(f"HTTP page {page}", response, percent=min(15 + page * 5, 60))
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")
            total_pages = max(total_pages, self._total_pages(soup))

            new_on_page = 0
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
                new_on_page += 1

            self._report(
                f"HTTP page {page}: new={new_on_page}, total={len(jobs)}",
                percent=min(20 + page * 5, 70),
                stage="Parsing results",
                jobs_seen=len(jobs),
            )

            page += 1

        if not jobs:
            raise ValueError("Charles Russell Speechlys current roles page returned no jobs")
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
        fetch_detail_pages: bool,
        max_pages: int,
        timeout: int,
    ) -> list[dict[str, Any]]:
        timeout_ms = timeout * 1000
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        page_number = 1
        total_pages = 1

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
                    extra_http_headers={
                        "Accept-Language": "en-GB,en;q=0.9",
                    },
                )
                page = await context.new_page()
                page.set_default_timeout(timeout_ms)

                while page_number <= total_pages:
                    if max_pages > 0 and page_number > max_pages:
                        break
                    page_url = self._page_url(source_url, page_number)
                    response = await page.goto(
                        page_url,
                        wait_until="domcontentloaded",
                        timeout=timeout_ms,
                    )
                    status = response.status if response else None
                    self._report(
                        f"Chromium page {page_number}: status={status or 'unknown'}, url={page.url}",
                        percent=min(45 + page_number * 5, 65),
                        stage="Browser loading",
                        jobs_seen=len(jobs),
                    )

                    await self._wait_for_browser_listing(page, timeout_ms)
                    soup = BeautifulSoup(await page.content(), "lxml")
                    total_pages = max(total_pages, self._total_pages(soup))

                    new_on_page = 0
                    for result in soup.select("li.roleListingResult"):
                        job = self._job_from_listing(result, page.url, page_number)
                        if not job:
                            continue

                        if fetch_detail_pages:
                            detail = await self._browser_detail(
                                context,
                                job["job_url"],
                                timeout_ms,
                            )
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
                        new_on_page += 1

                    if status is not None and status >= 400 and new_on_page == 0:
                        raise ValueError(await self._browser_block_message(page, status))

                    self._report(
                        f"Chromium page {page_number}: new={new_on_page}, total={len(jobs)}",
                        percent=min(50 + page_number * 5, 70),
                        stage="Browser parsing",
                        jobs_seen=len(jobs),
                    )
                    page_number += 1
            finally:
                await browser.close()

        if not jobs:
            raise ValueError("Charles Russell Speechlys browser fallback returned no jobs")
        self._report(
            f"Chromium path complete: jobs={len(jobs)}",
            percent=70,
            stage="Results ready",
            jobs_seen=len(jobs),
        )
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

        return self._detail_from_html(response.text, response.url)

    async def _browser_detail(
        self,
        context: Any,
        job_url: str,
        timeout_ms: int,
    ) -> dict[str, Any]:
        page = await context.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            response = await page.goto(
                job_url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            if response is not None and response.status >= 400:
                return {}
            return self._detail_from_html(await page.content(), page.url)
        except Exception:  # noqa: BLE001 - details are helpful but not required.
            return {}
        finally:
            await page.close()

    def _detail_from_html(self, html: str, page_url: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")
        title = self._clean_text(soup.select_one("h1.detailPageTitle"))
        description_html = soup.select_one('[data-epi-edit="JobAdvert"]')
        description = html_to_text(str(description_html)) if description_html else None
        fields = self._at_a_glance_fields(soup)
        apply_link = soup.select_one("a.rolePageApply[href]")
        apply_url = urljoin(page_url, str(apply_link.get("href"))) if apply_link else None

        return {
            "title": title,
            "office_location": fields.get("Location"),
            "practice_area": fields.get("Category"),
            "pqe_level": self._extract_pqe(title, description),
            "description": description,
            "source_reference": self._reference_from_url(page_url, apply_url),
            "extra_info": {
                "apply_url": apply_url,
                "contract_type": fields.get("Contract type"),
                "salary": fields.get("Salary"),
                "working_hours": fields.get("Working hours"),
                "description_source": "detail_page" if description else None,
            },
        }

    @classmethod
    def _request_headers(cls) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/137.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-GB,en;q=0.9",
            "Cache-Control": "no-cache",
            "Referer": "https://www.charlesrussellspeechlys.com/en/careers/",
            "Upgrade-Insecure-Requests": "1",
        }

    @staticmethod
    async def _wait_for_browser_listing(page: Any, timeout_ms: int) -> None:
        try:
            await page.locator(
                "li.roleListingResult, .searchPagePaginationInfo"
            ).first.wait_for(
                state="attached",
                timeout=min(timeout_ms, 10_000),
            )
        except PlaywrightTimeoutError:
            return

    @classmethod
    async def _browser_block_message(cls, page: Any, status: int) -> str:
        cookies = await page.context.cookies()
        cookie_names = sorted(
            str(cookie.get("name"))
            for cookie in cookies
            if cookie.get("name")
        )
        soup = BeautifulSoup(await page.content(), "lxml")
        preview = cls._clean(soup.get_text(" ", strip=True)) or ""
        return (
            f"browser page returned HTTP {status} without job rows "
            f"(url={page.url}, cookies={cookie_names}, preview={preview[:220] or 'empty'})"
        )

    def _report(
        self,
        message: str,
        *,
        percent: int,
        stage: str,
        jobs_seen: int = 0,
    ) -> None:
        line = f"[CRS {self.diagnostic_version}] {message}"
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
            f"{label}: status={response.status_code}, bytes={len(response.content)}, "
            f"url={response.url}, server={response.headers.get('server') or 'unknown'}",
            percent=percent,
            stage="Loading results",
        )

    @classmethod
    def _error_summary(cls, error: Exception | None) -> str:
        if error is None:
            return "unknown error"
        response = getattr(error, "response", None)
        if isinstance(response, requests.Response):
            preview = cls._clean(
                BeautifulSoup(response.text or "", "lxml").get_text(" ", strip=True)
            )
            return (
                f"{error} (status={response.status_code}, url={response.url}, "
                f"preview={(preview or 'empty')[:180]})"
            )
        return str(error)

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
