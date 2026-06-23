import re
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.async_api import Page, async_playwright

from app.plugins.base import BasePlugin


class AllHiresPlugin(BasePlugin):
    plugin_name = "allhires"
    display_name = "AllHires"
    discoverable = False
    enabled = True
    careers_url = None
    description = "Reusable scraper for AllHires-powered careers sites"
    required_config = ["source_url"]
    default_config = {
        "source_url": "",
        "fetch_detail_pages": False,
        "timeout_ms": 60_000,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        cfg = {**self.default_config, **(self.plugin_config or {})}
        source_url = str(cfg.get("source_url") or self.careers_url or "").strip()
        timeout_ms = int(cfg.get("timeout_ms") or 60_000)
        fetch_detail_pages = bool(cfg.get("fetch_detail_pages", True))

        if not source_url:
            raise ValueError("AllHires plugin requires source_url")

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/137.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1440, "height": 1000},
                    locale="en-US",
                )
                page = await context.new_page()
                page.set_default_timeout(timeout_ms)
                await page.goto(source_url, wait_until="networkidle", timeout=timeout_ms)
                await page.locator("a.header-link").first.wait_for(state="attached", timeout=timeout_ms)

                cards = await page.locator(".card.card-body:has(a.header-link)").evaluate_all(
                    """
                    cards => cards.map(card => {
                        const link = card.querySelector("a.header-link");
                        const fields = {};
                        card.querySelectorAll(".py-1.d-flex").forEach(row => {
                            const label = row.querySelector("b")?.textContent
                                ?.replace(":", "")
                                ?.trim();
                            const value = row.querySelector(".w-50:last-child")?.textContent
                                ?.replace(/\\s+/g, " ")
                                ?.trim();
                            if (label && value) fields[label] = value;
                        });
                        return {
                            title: link?.textContent?.replace(/\\s+/g, " ")?.trim() || "",
                            href: link?.href || "",
                            department: fields.Department || "",
                            location: fields.Location || "",
                            reference: fields.Reference || "",
                        };
                    })
                    """
                )

                for card in cards:
                    title = self._clean(card.get("title"))
                    job_url = self._clean(card.get("href"))
                    reference = self._clean(card.get("reference")) or self._reference_from_url(job_url)
                    if not title or not job_url or not reference or reference in seen:
                        continue

                    seen.add(reference)
                    detail = await self._fetch_detail(page, job_url, timeout_ms) if fetch_detail_pages else {}

                    jobs.append(
                        {
                            "job_url": job_url,
                            "firm_name": self.firm_name,
                            "title": detail.get("title") or title,
                            "office_location": detail.get("location") or self._clean(card.get("location")),
                            "practice_area": detail.get("department") or self._clean(card.get("department")),
                            "pqe_level": detail.get("experience_level"),
                            "description": detail.get("description"),
                            "source_reference": reference,
                            "status": "LIVE",
                            "extra_info": {
                                "source": "allhires",
                                "reference": reference,
                                "term_type": detail.get("term_type"),
                                "description_source": "detail_page" if detail.get("description") else None,
                            },
                        }
                    )
            finally:
                await browser.close()

        return jobs

    async def _fetch_detail(self, page: Page, job_url: str, timeout_ms: int) -> dict[str, str | None]:
        try:
            await page.goto(job_url, wait_until="networkidle", timeout=timeout_ms)
            text = await page.locator("body").inner_text(timeout=timeout_ms)
        except Exception:
            return {}

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = lines[3] if len(lines) > 3 and lines[2].endswith("Position details") else None

        fields = {
            "experience_level": self._field_after(lines, "Experience level:"),
            "term_type": self._field_after(lines, "Term type:"),
            "department": self._field_after(lines, "Department:"),
            "location": self._field_after(lines, "Location:"),
        }
        description = self._detail_description(lines)

        return {
            "title": title,
            "description": description,
            **fields,
        }

    @staticmethod
    def _detail_description(lines: list[str]) -> str | None:
        if not lines:
            return None

        start = 0
        for index, line in enumerate(lines):
            if line == "Location:" and index + 2 < len(lines):
                start = index + 2
                break

        stop_markers = {
            "Apply",
            "Register",
            "Login",
            "Privacy policy | Terms of Use | Contact us",
            "AllHires online application system.",
        }
        body: list[str] = []
        for line in lines[start:]:
            if line in stop_markers or line.startswith("AllHires online application system."):
                break
            body.append(line)

        text = "\n".join(body).strip()
        return text or None

    @staticmethod
    def _field_after(lines: list[str], label: str) -> str | None:
        for index, line in enumerate(lines):
            if line == label and index + 1 < len(lines):
                value = lines[index + 1].strip()
                return value or None
        return None

    @staticmethod
    def _reference_from_url(url: str | None) -> str | None:
        if not url:
            return None
        query = parse_qs(urlparse(url).query)
        value = query.get("id", [None])[0]
        return str(value).strip() if value else None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", str(value)).strip()
        return text or None
