from typing import Any
from urllib.parse import urljoin

from playwright.async_api import async_playwright

from app.plugins.base import BasePlugin


class PlaywrightExamplePlugin(BasePlugin):
    """Example plugin for dynamic sites rendered in the browser."""

    plugin_name = "playwright_example"
    display_name = "Playwright Example Firm"
    enabled = False
    careers_url = "https://example.com/careers"
    description = "Example plugin scraping dynamic content with Playwright"
    required_config = ["start_url", "card_selector", "title_selector", "link_selector"]
    default_config = {
        "start_url": "https://example.com/careers",
        "card_selector": ".job-card",
        "title_selector": "h2",
        "link_selector": "a",
        "location_selector": ".location",
        "practice_selector": ".practice-area",
        "pqe_selector": ".pqe",
        "description_selector": ".description",
        "reference_selector": "[data-job-id]",
        "wait_for_selector": ".job-card",
        "wait_until": "networkidle",
        "headless": True,
        "timeout_ms": 30000,
        "max_jobs": 200,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        cfg = {**self.default_config, **(self.plugin_config or {})}
        start_url = str(cfg["start_url"])
        card_selector = str(cfg["card_selector"])
        title_selector = str(cfg["title_selector"])
        link_selector = str(cfg["link_selector"])
        location_selector = str(cfg.get("location_selector") or "")
        practice_selector = str(cfg.get("practice_selector") or "")
        pqe_selector = str(cfg.get("pqe_selector") or "")
        description_selector = str(cfg.get("description_selector") or "")
        reference_selector = str(cfg.get("reference_selector") or "")
        wait_for_selector = str(cfg.get("wait_for_selector") or "")
        wait_until = str(cfg.get("wait_until") or "networkidle")
        timeout_ms = int(cfg.get("timeout_ms") or 30000)
        max_jobs = max(1, int(cfg.get("max_jobs") or 200))
        html = cfg.get("html")

        jobs: list[dict[str, Any]] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=bool(cfg.get("headless", True)))
            page = await browser.new_page()
            try:
                if isinstance(html, str) and html.strip():
                    await page.set_content(html, wait_until="domcontentloaded")
                    base_url = start_url
                else:
                    await page.goto(start_url, wait_until=wait_until, timeout=timeout_ms)
                    if wait_for_selector:
                        await page.wait_for_selector(wait_for_selector, timeout=timeout_ms)
                    base_url = page.url

                cards = await page.query_selector_all(card_selector)
                for card in cards[:max_jobs]:
                    title = await _text(card, title_selector)
                    href = await _attr(card, link_selector, "href")
                    job_url = urljoin(base_url, href) if href else None

                    if not title and not job_url:
                        continue

                    jobs.append(
                        {
                            "job_url": job_url,
                            "firm_name": self.firm_name,
                            "title": title,
                            "office_location": await _text(card, location_selector),
                            "practice_area": await _text(card, practice_selector),
                            "pqe_level": await _text(card, pqe_selector),
                            "description": await _text(card, description_selector),
                            "source_reference": await _attr(card, reference_selector, "data-job-id"),
                            "status": "LIVE",
                            "extra_info": {
                                "source": "playwright_example",
                            },
                        }
                    )
            finally:
                await browser.close()

        return jobs


async def _text(card, selector: str) -> str | None:
    if not selector:
        return None
    el = await card.query_selector(selector)
    if el is None:
        return None
    text = (await el.text_content()) or ""
    cleaned = " ".join(text.split())
    return cleaned or None


async def _attr(card, selector: str, name: str) -> str | None:
    if not selector:
        return None
    el = await card.query_selector(selector)
    if el is None:
        return None
    value = await el.get_attribute(name)
    return value.strip() if value else None

