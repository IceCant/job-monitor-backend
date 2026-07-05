from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class OsborneClarkePlugin(BasePlugin):
    plugin_name = "osborne_clarke"
    display_name = "Osborne Clarke"
    enabled = True
    careers_url = "https://careers.osborneclarke.com/vacancies/vacancy-search-results.aspx"
    description = "Osborne Clarke Eploy careers scraper"
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
                )
            }
        )

        response = session.get(source_url, timeout=timeout)
        self._prepare_response(response)
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 1
        total_pages: int | None = None

        while True:
            soup = BeautifulSoup(response.text, "lxml")
            total_pages = total_pages or self._total_pages(soup)
            before = len(jobs)
            self._append_jobs(soup, response.url, page, jobs, seen)
            if len(jobs) == before:
                break
            if max_pages > 0 and page >= max_pages:
                break
            if page >= total_pages:
                break

            next_page = page + 1
            response = self._fetch_page(session, soup, response.url, next_page, timeout)
            page = next_page

        return jobs

    def _append_jobs(
        self,
        soup: BeautifulSoup,
        page_url: str,
        page: int,
        jobs: list[dict[str, Any]],
        seen: set[str],
    ) -> None:
        for card in soup.select(".vsr-job-big"):
            link = card.select_one(".vsr-job__title a[href]")
            if link is None:
                continue

            href = str(link.get("href") or "").strip()
            title = self._clean(link.get_text(" ", strip=True))
            job_url = urljoin(page_url, href)
            reference = self._reference(job_url)
            if not href or not title or not reference or reference in seen:
                continue

            fields = self._fields(card)
            seen.add(reference)
            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": fields.get("All Locations"),
                    "practice_area": fields.get("Position"),
                    "pqe_level": None,
                    "description": self._text(card, ".vsr-job__desc"),
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "osborne_clarke_eploy_html",
                        "listing_page": page,
                        "posted_date": self._posted_date(card),
                        "function": fields.get("Function"),
                        "contract_type": fields.get("Contract Type"),
                    },
                }
            )

    def _fetch_page(
        self,
        session: requests.Session,
        soup: BeautifulSoup,
        current_url: str,
        page: int,
        timeout: int,
    ) -> requests.Response:
        form = soup.select_one("form#aspnetForm")
        if form is None:
            raise ValueError("Osborne Clarke pagination form was not found")

        event_target = self._pager_target(soup)
        if not event_target:
            raise ValueError("Osborne Clarke pagination target was not found")

        data: dict[str, str] = {}
        for element in form.select('input[type="hidden"]'):
            name = str(element.get("name") or "").strip()
            if name:
                data[name] = str(element.get("value") or "")
        data["__EVENTTARGET"] = event_target
        data["__EVENTARGUMENT"] = str(page)

        action = urljoin(current_url, str(form.get("action") or current_url))
        response = session.post(action, data=data, timeout=timeout)
        self._prepare_response(response)
        return response

    @classmethod
    def _total_pages(cls, soup: BeautifulSoup) -> int:
        pages = [int(argument) for _, argument in cls._pager_links(soup)]
        return max(pages, default=1)

    @classmethod
    def _pager_target(cls, soup: BeautifulSoup) -> str | None:
        links = cls._pager_links(soup)
        return links[0][0] if links else None

    @staticmethod
    def _pager_links(soup: BeautifulSoup) -> list[tuple[str, str]]:
        links: list[tuple[str, str]] = []
        pattern = re.compile(r"__doPostBack\('([^']*VacancyPager)','(\d+)'\)")
        for link in soup.select("a[href*='__doPostBack'][href*='VacancyPager']"):
            match = pattern.search(str(link.get("href") or ""))
            if match and not match.group(1).endswith("VacancyPager2"):
                links.append((match.group(1), match.group(2)))
        return links

    @classmethod
    def _fields(cls, card: Any) -> dict[str, str]:
        fields: dict[str, str] = {}
        for item in card.select(".vsr-job__list-item"):
            label_el = item.select_one("[data-tooltip]")
            label = cls._clean(label_el.get("data-tooltip") if label_el else None)
            if not label:
                continue

            value_el = (
                item.select_one('[id$="_lblReadonlySelected"]')
                or item.select_one(".content span[data-selectedvalue]")
                or item.select_one(".content > span")
            )
            value = cls._clean(value_el.get_text(" ", strip=True) if value_el else None)
            if value and value.casefold() != "not specified":
                fields[label] = value
        return fields

    @classmethod
    def _posted_date(cls, card: Any) -> str | None:
        value = cls._text(card, ".vsr-job__date-posted")
        if not value:
            return None
        return re.sub(r"^Posted\s+on\s+", "", value, flags=re.IGNORECASE).strip() or None

    @staticmethod
    def _reference(job_url: str) -> str | None:
        parts = [part for part in urlparse(job_url).path.split("/") if part]
        for part in parts:
            if part.isdigit():
                return part
        values = parse_qs(urlparse(job_url).query).get("VacancyID")
        return values[0] if values else None

    @classmethod
    def _text(cls, root: Any, selector: str) -> str | None:
        element = root.select_one(selector) if root else None
        if element is None:
            return None
        return cls._clean(element.get_text(" ", strip=True))

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
