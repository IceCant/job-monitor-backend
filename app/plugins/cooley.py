from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from app.plugins.base import BasePlugin


class CooleyPlugin(BasePlugin):
    """Example plugin showing how to parse HTML cards with BeautifulSoup."""

    plugin_name = "cooley"
    display_name = "Cooley"
    enabled = True
    careers_url = "https://lawcruit.micronapps.com/sup/lc_supp_jobpost.aspx?%40Pl3%3cKWEX%40=1n34&%3db8=8_CG"
    description = "Cooley"
    required_config = ["source_url"]
    default_config = {
        "source_url": "https://lawcruit.micronapps.com/sup/lc_supp_jobpost.aspx?%40Pl3%3cKWEX%40=1n34&%3db8=8_CG",
        # "card_selector": ".job-card",
        # "title_selector": "h2",
        # "location_selector": ".location",
        # "link_selector": "a",
    }

    async def scrape(self) -> list[dict[str, Any]]:
        jobs = []
        source_url = self.plugin_config.get("source_url")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, channel="chrome")

            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
                locale="en-US",
            )

            page = await context.new_page()
            await page.goto(source_url, wait_until="networkidle", timeout=60000)

            seen_urls = set()
            page_no = 1

            while True:
                print(f"Scraping page {page_no}: {page.url}")

                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                rows = soup.select("div.card.card-hover")
                for row in rows:
                    title_el = row.select_one("a.linkbutton.page-header")
                    job_id_el = row.select_one("input[id$='_jobId']")

                    if not title_el or not job_id_el:
                        continue

                    title = title_el.get_text(" ", strip=True)
                    job_id = job_id_el.get("value", "").strip()

                    # location + posted date
                    info_rows = row.select(".col-12.sub-title")

                    location = None
                    posted_date = None

                    if len(info_rows) >= 1:
                        location_text = info_rows[0].get_text(" ", strip=True)
                        # Example: "Boston 10 Jun 2026"
                        posted_el = info_rows[0].select_one(".float-right")
                        posted_date = posted_el.get_text(" ", strip=True) if posted_el else None

                        if posted_date:
                            location = location_text.replace(posted_date, "").strip()
                        else:
                            location = location_text.strip()

                    description_el = row.select_one(".block-ellipsis")
                    description = (
                        description_el.get_text(" ", strip=True)
                        if description_el
                        else None
                    )

                    # href is javascript, so don't use it as real URL
                    job_url = f"{source_url}#{job_id}"

                    if job_url in seen_urls:
                        continue
                    seen_urls.add(job_url)

                    jobs.append({
                        "firm_name": "Cooley",
                        "title": title,
                        "job_url": job_url,
                        "source_reference": job_id,
                        "office_location": location,
                        # "posted_date": posted_date,
                        "practice_area": None,
                        "pqe_level": None,
                        "description": description,
                        "status": "LIVE",
                    })
                # Find real Next link
                next_link = page.locator("a#m_body_pnlPager_pager_pageNext")

                if await next_link.count() == 0:
                    break

                first_next = next_link.first

                # Stop if disabled
                class_name = await first_next.get_attribute("class") or ""
                href = await first_next.get_attribute("href")

                if "aspNetDisabled" in class_name or not href:
                    break

                old_html = html

                await first_next.click()
                await page.wait_for_load_state("networkidle")

                new_html = await page.content()

                if new_html == old_html:
                    break

                page_no += 1

            await browser.close()

        return jobs


# def _extract_reference(href: str) -> str:
#     clean = href.strip("/")
#     return clean.split("/")[-1] or clean


