from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class TwoBirdsPlugin(BasePlugin):
    """Example plugin showing how to parse HTML cards with BeautifulSoup."""

    plugin_name = "twobirds"
    display_name = "Two Birds"
    enabled = True
    careers_url = "https://fsr.cvmailuk.com/twobirds/main.cfm?page=jobBoard&fo=1&groupType_8=&groupType_6=&filter=&srxksl=1"
    description = "Test with two birds"
    required_config = ["source_url"]
    default_config = {
        "source_url": "https://fsr.cvmailuk.com/twobirds/main.cfm?page=jobBoard&fo=1&groupType_8=&groupType_6=&filter=&srxksl=1",
        # "card_selector": ".job-card",
        # "title_selector": "h2",
        # "location_selector": ".location",
        # "link_selector": "a",
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

        soup = BeautifulSoup(html, "lxml")
        card_selector = self.plugin_config.get("card_selector", "table.cvmJobBoardHeader tr.even, table.cvmJobBoardHeader tr.odd")
        title_selector = self.plugin_config.get("title_selector", "a.jobMoreDetailCaptionStyle")
        area_selector = self.plugin_config.get("area_selector", ":nth-last-child(2)")
        location_selector = self.plugin_config.get("location_selector", "td.jbTableTextStyle:last-child")
        link_selector = self.plugin_config.get("link_selector", "a.jobMoreDetailCaptionStyle")

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

            job_url = _canonical_job_url(source_url, href)
            reference = _extract_reference(href)

            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": (
                        card.select_one(location_selector).get_text(strip=True)
                        if card.select_one(location_selector)
                        else None
                    ),
                    "practice_area": (
                        card.select_one(area_selector).get_text(strip=True)
                        if card.select_one(area_selector)
                        else None
                    ),
                    "pqe_level": self.plugin_config.get("pqe_level"),
                    "description": (
                        card.select_one(self.plugin_config.get("description_selector", ".description")).get_text(strip=True)
                        if card.select_one(self.plugin_config.get("description_selector", ".description"))
                        else None
                    ),
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "twobirds",
                        "raw_job_url": urljoin(source_url, href),
                    },
                }
            )

        return jobs


def _extract_reference(href: str) -> str:
    query = parse_qs(urlparse(href).query)
    job_id = _first_query_value(query, "jobId")
    if job_id:
        return job_id

    clean = _canonical_path_with_query(href)
    return clean or href.strip("/")


def _canonical_job_url(source_url: str, href: str) -> str:
    absolute = urljoin(source_url, href)
    parsed = urlparse(absolute)
    query = parse_qs(parsed.query)
    job_id = _first_query_value(query, "jobId")
    if not job_id:
        return urlunparse(parsed._replace(query=urlencode(_stable_query(query), doseq=True)))

    stable_query = urlencode(
        {
            "page": "jobSpecific",
            "jobId": job_id,
            "srxksl": _first_query_value(query, "srxksl") or "1",
        }
    )
    return urlunparse(parsed._replace(query=stable_query))


def _canonical_path_with_query(href: str) -> str:
    parsed = urlparse(href)
    query = urlencode(_stable_query(parse_qs(parsed.query)), doseq=True)
    return urlunparse(parsed._replace(query=query)).strip("/")


def _stable_query(query: dict[str, list[str]]) -> dict[str, list[str]]:
    volatile_keys = {"rcd", "queryString", "x-token"}
    return {
        key: values
        for key, values in query.items()
        if key not in volatile_keys
    }


def _first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    value = str(values[0]).strip()
    return value or None

