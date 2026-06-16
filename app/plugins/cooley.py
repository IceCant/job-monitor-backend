import asyncio
import re
from typing import Any

from bs4 import BeautifulSoup
from playwright.async_api import (
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from app.plugins.base import BasePlugin


class ScrapeIncompleteError(RuntimeError):
    pass


class CooleyPlugin(BasePlugin):
    plugin_name = "cooley"
    display_name = "Cooley"
    enabled = True

    careers_url = (
        "https://lawcruit.micronapps.com/sup/"
        "lc_supp_jobpost.aspx?%40Pl3%3cKWEX%40=1n34&%3db8=8_CG"
    )

    description = "Cooley"
    required_config = ["source_url"]

    default_config = {
        "source_url": careers_url,
        "max_pages": 100,
        "pagination_retries": 3,
    }

    CARD_SELECTOR = "div.card.card-hover"
    JOB_ID_SELECTOR = "input[id$='_jobId']"

    NEXT_LINK_SELECTOR = "#m_body_pnlPager_pager_pageNext"
    NEXT_ITEM_SELECTOR = "#m_body_pnlPager_pager_liNext"

    PAGINATION_TEXT_SELECTOR = ".pagination-text"

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = self.plugin_config["source_url"]
        max_pages = int(self.plugin_config.get("max_pages", 100))
        retries = int(self.plugin_config.get("pagination_retries", 3))

        jobs: list[dict[str, Any]] = []
        seen_job_ids: set[str] = set()
        seen_page_signatures: set[tuple[str, ...]] = set()

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                )

                page = await context.new_page()
                page.set_default_timeout(30_000)

                await page.goto(
                    source_url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )

                await self._wait_for_jobs(page)

                for loop_page_no in range(1, max_pages + 1):
                    await self._wait_for_jobs(page)

                    html = await page.content()
                    page_jobs = self._parse_jobs(html, source_url)

                    if not page_jobs:
                        raise ScrapeIncompleteError(
                            f"No jobs found on pagination iteration "
                            f"{loop_page_no}."
                        )

                    signature = tuple(
                        job["source_reference"] for job in page_jobs
                    )

                    if signature in seen_page_signatures:
                        raise ScrapeIncompleteError(
                            f"Repeated job page detected at iteration "
                            f"{loop_page_no}."
                        )

                    seen_page_signatures.add(signature)

                    pagination = await self._get_pagination_info(page)

                    print(
                        f"Page iteration: {loop_page_no}, "
                        f"rows={pagination}, "
                        f"jobs={len(page_jobs)}"
                    )

                    for job in page_jobs:
                        job_id = job["source_reference"]

                        if job_id in seen_job_ids:
                            continue

                        seen_job_ids.add(job_id)
                        jobs.append(job)

                    if self._is_last_page_from_rows(pagination):
                        print(
                            "Last page confirmed using pagination row count."
                        )
                        break

                    moved = await self._click_next_and_wait(
                        page=page,
                        old_signature=signature,
                        retries=retries,
                    )

                    if not moved:
                        # Check pagination text again. It may have reached the
                        # last page even if DOM state did not fully update.
                        pagination = await self._get_pagination_info(page)

                        if self._is_last_page_from_rows(pagination):
                            print(
                                "Last page confirmed after pagination timeout."
                            )
                            break

                        raise ScrapeIncompleteError(
                            "Next page could not be loaded reliably. "
                            f"Current pagination: {pagination}. "
                            f"Collected {len(jobs)} jobs."
                        )
                else:
                    raise ScrapeIncompleteError(
                        f"Reached max_pages={max_pages}. "
                        "Possible infinite pagination loop."
                    )

                return jobs

            finally:
                await browser.close()

    async def _wait_for_jobs(self, page: Page) -> None:
        await page.locator(self.CARD_SELECTOR).first.wait_for(
            state="visible",
            timeout=30_000,
        )

        await page.wait_for_function(
            """
            selector => {
                const elements = document.querySelectorAll(selector);

                return Array.from(elements).some(element => {
                    return element.value && element.value.trim();
                });
            }
            """,
            arg=self.JOB_ID_SELECTOR,
            timeout=30_000,
        )

    async def _get_job_signature(
        self,
        page: Page,
    ) -> tuple[str, ...]:
        job_ids = await page.locator(
            self.JOB_ID_SELECTOR
        ).evaluate_all(
            """
            elements => elements
                .map(element => element.value?.trim())
                .filter(Boolean)
            """
        )

        return tuple(job_ids)

    async def _get_pagination_info(
        self,
        page: Page,
    ) -> dict[str, int] | None:
        """
        Parses text like:

        Rows 1 - 20 of 144
        Rows 141 - 144 of 144
        """

        pagination_text = page.locator(
            self.PAGINATION_TEXT_SELECTOR
        ).first

        if await pagination_text.count() == 0:
            return None

        text = await pagination_text.inner_text()
        text = " ".join(text.split())

        match = re.search(
            r"Rows\s+(\d+)\s*-\s*(\d+)\s+of\s+(\d+)",
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            return None

        return {
            "start": int(match.group(1)),
            "end": int(match.group(2)),
            "total": int(match.group(3)),
        }

    def _is_last_page_from_rows(
        self,
        pagination: dict[str, int] | None,
    ) -> bool:
        if not pagination:
            return False

        return pagination["end"] >= pagination["total"]

    async def _is_next_disabled(self, page: Page) -> bool:
        next_item = page.locator(self.NEXT_ITEM_SELECTOR)
        next_link = page.locator(self.NEXT_LINK_SELECTOR)

        if await next_item.count() == 0:
            return False

        item_class = (
            await next_item.first.get_attribute("class") or ""
        )

        if await next_link.count() == 0:
            return "disabled" in item_class.split()

        link_class = (
            await next_link.first.get_attribute("class") or ""
        )

        href = await next_link.first.get_attribute("href")
        aria_disabled = await next_link.first.get_attribute(
            "aria-disabled"
        )

        return any(
            [
                "disabled" in item_class.split(),
                "aspNetDisabled" in link_class.split(),
                "disabled" in link_class.split(),
                not href,
                aria_disabled == "true",
            ]
        )

    async def _click_next_and_wait(
        self,
        page: Page,
        old_signature: tuple[str, ...],
        retries: int,
    ) -> bool:
        old_signature_string = "|".join(old_signature)

        for attempt in range(1, retries + 1):
            pagination_before = await self._get_pagination_info(page)

            if self._is_last_page_from_rows(pagination_before):
                return False

            if await self._is_next_disabled(page):
                return False

            next_link = page.locator(
                self.NEXT_LINK_SELECTOR
            ).first

            if await next_link.count() == 0:
                print(
                    f"Next link not found, attempt "
                    f"{attempt}/{retries}."
                )

                await asyncio.sleep(attempt)
                continue

            try:
                await next_link.scroll_into_view_if_needed()

                await next_link.click(timeout=15_000)

                # Wait until either:
                # 1. job IDs change, or
                # 2. pagination starting row changes.
                await page.wait_for_function(
                    """
                    args => {
                        const jobIds = Array.from(
                            document.querySelectorAll(args.jobSelector)
                        )
                        .map(element => element.value?.trim())
                        .filter(Boolean)
                        .join("|");

                        const paginationElement =
                            document.querySelector(args.paginationSelector);

                        const paginationText =
                            paginationElement?.textContent
                                ?.replace(/\\s+/g, " ")
                                .trim() || "";

                        return (
                            jobIds !== args.oldSignature ||
                            paginationText !== args.oldPaginationText
                        );
                    }
                    """,
                    arg={
                        "jobSelector": self.JOB_ID_SELECTOR,
                        "paginationSelector":
                            self.PAGINATION_TEXT_SELECTOR,
                        "oldSignature": old_signature_string,
                        "oldPaginationText": (
                            self._format_pagination(pagination_before)
                        ),
                    },
                    timeout=25_000,
                )

                await self._wait_for_jobs(page)

                new_signature = await self._get_job_signature(page)
                pagination_after = await self._get_pagination_info(page)

                if new_signature != old_signature:
                    return True

                if pagination_after != pagination_before:
                    return True

            except PlaywrightTimeoutError:
                new_signature = await self._get_job_signature(page)
                pagination_after = await self._get_pagination_info(page)

                if new_signature != old_signature:
                    return True

                if pagination_after != pagination_before:
                    return True

                if self._is_last_page_from_rows(pagination_after):
                    return False

                print(
                    f"Next click did not change page, "
                    f"attempt {attempt}/{retries}."
                )

            except Exception as exc:
                print(
                    f"Next click failed on attempt "
                    f"{attempt}/{retries}: "
                    f"{type(exc).__name__}: {exc}"
                )

            await asyncio.sleep(attempt)

        return False

    def _format_pagination(
        self,
        pagination: dict[str, int] | None,
    ) -> str:
        if not pagination:
            return ""

        return (
            f"Rows {pagination['start']} - "
            f"{pagination['end']} of "
            f"{pagination['total']}"
        )

    def _parse_jobs(
        self,
        html: str,
        source_url: str,
    ) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select(self.CARD_SELECTOR)

        jobs: list[dict[str, Any]] = []

        for row in rows:
            title_el = row.select_one(
                "a.linkbutton.page-header"
            )
            job_id_el = row.select_one(
                self.JOB_ID_SELECTOR
            )

            if not title_el or not job_id_el:
                continue

            title = title_el.get_text(" ", strip=True)
            job_id = job_id_el.get("value", "").strip()

            if not title or not job_id:
                continue

            info_row = row.select_one(
                ".col-12.sub-title"
            )

            location = None
            posted_date = None

            if info_row:
                posted_el = info_row.select_one(
                    ".float-right"
                )

                if posted_el:
                    posted_date = posted_el.get_text(
                        " ",
                        strip=True,
                    )
                    posted_el.extract()

                location = (
                    info_row.get_text(" ", strip=True)
                    or None
                )

            description_el = row.select_one(
                ".block-ellipsis"
            )

            description = (
                description_el.get_text(" ", strip=True)
                if description_el
                else None
            )

            jobs.append(
                {
                    "firm_name": self.display_name,
                    "title": title,
                    "job_url": f"{source_url}#{job_id}",
                    "source_reference": job_id,
                    "office_location": location,
                    # "posted_date": posted_date,
                    "practice_area": None,
                    "pqe_level": None,
                    "description": description,
                    "status": "LIVE",
                }
            )

        return jobs