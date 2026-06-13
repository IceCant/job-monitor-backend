from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class Bs4ExamplePlugin(BasePlugin):
    """Example plugin showing how to parse HTML cards with BeautifulSoup."""

    plugin_name = "hsfkramer"
    display_name = "Herbert Smith Freehills Kramer"
    enabled = False
    careers_url = "https://careers.hsfkramer.com/global/en/search-results"
    description = "Example plugin scraping simple HTML with BeautifulSoup"
    required_config = ["source_url"]
    default_config = {
        "source_url": "https://careers.hsfkramer.com/global/en/search-results",
        "card_selector": ".job-card",
        "title_selector": "h2",
        "location_selector": ".location",
        "link_selector": "a",
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = self.plugin_config.get("source_url")
        if not source_url:
            raise ValueError("bs4_example plugin requires 'source_url' in plugin_config")

        html = self.plugin_config.get("html")
        if not html:
            response = requests.get(source_url, timeout=30)
            response.raise_for_status()
            html = response.text

        soup = BeautifulSoup(html, "html.parser")
        card_selector = self.plugin_config.get("card_selector", ".job-card")
        title_selector = self.plugin_config.get("title_selector", "h2")
        location_selector = self.plugin_config.get("location_selector", ".location")
        link_selector = self.plugin_config.get("link_selector", "a")

        jobs: list[dict[str, Any]] = []
        for card in soup.select(card_selector):
            title_el = card.select_one(title_selector)
            link_el = card.select_one(link_selector)
            if title_el is None or link_el is None:
                continue

            title = title_el.get_text(strip=True)

            href = (link_el.get("href") or "").strip()
            if not href:
                continue

            jobs.append(
                {
                    "job_url": urljoin(source_url, href),
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": (
                        card.select_one(location_selector).get_text(strip=True)
                        if card.select_one(location_selector)
                        else None
                    ),
                    "practice_area": self.plugin_config.get("practice_area"),
                    "pqe_level": self.plugin_config.get("pqe_level"),
                    "description": (
                        card.select_one(self.plugin_config.get("description_selector", ".description")).get_text(strip=True)
                        if card.select_one(self.plugin_config.get("description_selector", ".description"))
                        else None
                    ),
                    "source_reference": _extract_reference(href),
                    "status": "LIVE",
                    "extra_info": {
                        "source": "bs4_example",
                    },
                }
            )

        return jobs


def _extract_reference(href: str) -> str:
    clean = href.strip("/")
    return clean.split("/")[-1] or clean


