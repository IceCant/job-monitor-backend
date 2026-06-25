import re
import time
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class StephensonHarwoodPlugin(BasePlugin):
    plugin_name = "stephenson_harwood"
    display_name = "Stephenson Harwood"
    enabled = True
    careers_url = "https://www.linkedin.com/jobs/stephenson-harwood-llp-jobs-worldwide?f_C=19553"
    description = "Stephenson Harwood LinkedIn public jobs scraper"
    required_config = ["source_url"]
    default_config = {
        "source_url": "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search",
        "company_jobs_url": "https://www.linkedin.com/jobs/stephenson-harwood-llp-jobs-worldwide?f_C=19553",
        "company_id": "19553",
        "keywords": "Stephenson Harwood Llp",
        "location": "Worldwide",
        "geo_id": "92000000",
        "locations": ["Worldwide"],
        "page_size": 10,
        "max_pages": 0,
        "fetch_detail_pages": True,
        "max_detail_pages": 0,
        "request_delay_seconds": 1.25,
        "max_retries": 2,
        "safety_max_pages": 100,
        "timeout": 30,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = self.plugin_config.get("source_url") or self.default_config["source_url"]
        timeout = int(self.plugin_config.get("timeout", 30))
        page_size = int(self.plugin_config.get("page_size", 25))
        max_pages = int(self.plugin_config.get("max_pages", 0))
        safety_max_pages = int(self.plugin_config.get("safety_max_pages", 100))
        fetch_detail_pages = bool(self.plugin_config.get("fetch_detail_pages", True))
        max_detail_pages = int(self.plugin_config.get("max_detail_pages", 0))
        request_delay_seconds = float(self.plugin_config.get("request_delay_seconds", 1.25))
        max_retries = int(self.plugin_config.get("max_retries", 2))

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
            }
        )

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        detail_pages_fetched = 0

        def append_page_jobs(page_jobs: list[dict[str, Any]]) -> int:
            nonlocal detail_pages_fetched
            new_jobs_on_page = 0
            for job in page_jobs:
                reference = job["source_reference"]
                if reference in seen:
                    continue
                seen.add(reference)
                new_jobs_on_page += 1

                should_fetch_detail = fetch_detail_pages and (
                    max_detail_pages <= 0 or detail_pages_fetched < max_detail_pages
                )
                if should_fetch_detail:
                    detail = self._fetch_detail(
                        session,
                        reference,
                        timeout,
                        max_retries=max_retries,
                    )
                    detail_pages_fetched += 1
                    job.update(
                        {
                            "title": detail.get("title") or job["title"],
                            "office_location": detail.get("office_location") or job["office_location"],
                            "description": detail.get("description") or job["description"],
                        }
                    )
                    job["extra_info"].update(detail.get("extra_info", {}))

                jobs.append(job)
                if request_delay_seconds > 0:
                    time.sleep(request_delay_seconds)
            return new_jobs_on_page

        company_jobs_url = str(self.plugin_config.get("company_jobs_url") or "").strip()
        if company_jobs_url:
            response = self._get_with_retry(
                session,
                company_jobs_url,
                timeout=timeout,
                max_retries=max_retries,
            )
            if response is not None:
                append_page_jobs(
                    self._parse_search_page(
                        response.text,
                        query_location=str(self.plugin_config.get("location") or "Worldwide"),
                    )
                )

        for location in self._locations():
            page = 0
            start = 0
            while True:
                if max_pages > 0 and page >= max_pages:
                    break
                if page >= safety_max_pages:
                    break

                response = self._get_with_retry(
                    session,
                    source_url,
                    params=self._search_params(start=start, location=location),
                    timeout=timeout,
                    max_retries=max_retries,
                )
                if response is None:
                    break

                raw_card_count = self._search_card_count(response.text)
                page_jobs = self._parse_search_page(response.text, query_location=location)
                if raw_card_count == 0:
                    break

                new_jobs_on_page = append_page_jobs(page_jobs)

                page += 1
                start += raw_card_count or page_size
                if new_jobs_on_page == 0:
                    break

        return jobs

    def _locations(self) -> list[str]:
        locations = self.plugin_config.get("locations") or []
        if isinstance(locations, str):
            locations = [item.strip() for item in locations.split(",")]
        locations = [str(item).strip() for item in locations if str(item).strip()]
        if locations:
            return locations

        location = str(self.plugin_config.get("location") or "").strip()
        return [location or "Worldwide"]

    def _search_params(self, *, start: int, location: str) -> dict[str, Any]:
        params: dict[str, Any] = {
            "keywords": self.plugin_config.get("keywords") or "Stephenson Harwood Llp",
            "start": start,
        }
        if location:
            params["location"] = location
        company_id = str(self.plugin_config.get("company_id") or "").strip()
        if company_id:
            params["f_C"] = company_id
        geo_id = str(self.plugin_config.get("geo_id") or "").strip()
        if geo_id:
            params["geoId"] = geo_id
        return params

    def _parse_search_page(self, html: str, *, query_location: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[dict[str, Any]] = []

        for card in soup.select(".job-search-card"):
            company = self._text(card, ".base-search-card__subtitle")
            if company and "stephenson harwood" not in company.lower():
                continue

            title = self._text(card, ".base-search-card__title")
            link = card.select_one("a.base-card__full-link[href]")
            job_url = self._canonical_job_url(link.get("href") if link else None)
            reference = self._job_id_from_card(card, job_url)

            if not title or not job_url or not reference:
                continue

            date_el = card.select_one("time[datetime]")
            posted_date = date_el.get("datetime") if date_el else None

            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": self._text(card, ".job-search-card__location"),
                    "practice_area": None,
                    "pqe_level": None,
                    "description": None,
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "linkedin_guest_search",
                        "company": company,
                        "query_location": query_location,
                        "posted_date": posted_date,
                        "benefits": self._text(card, ".job-posting-benefits__text"),
                    },
                }
            )

        return jobs

    @staticmethod
    def _search_card_count(html: str) -> int:
        soup = BeautifulSoup(html, "html.parser")
        return len(soup.select(".job-search-card"))

    def _fetch_detail(
        self,
        session: requests.Session,
        job_id: str,
        timeout: int,
        max_retries: int,
    ) -> dict[str, Any]:
        detail_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
        response = self._get_with_retry(
            session,
            detail_url,
            timeout=timeout,
            max_retries=max_retries,
        )
        if response is None:
            return {}

        soup = BeautifulSoup(response.text, "html.parser")
        criteria = self._parse_criteria(soup)
        description_html = soup.select_one(".show-more-less-html__markup")
        description = self._html_to_text(str(description_html)) if description_html else None

        return {
            "title": self._text(soup, ".topcard__title"),
            "office_location": self._topcard_location(soup),
            "description": description,
            "extra_info": {
                "detail_source": "linkedin_guest_detail",
                "detail_url": detail_url,
                "seniority_level": criteria.get("Seniority level"),
                "employment_type": criteria.get("Employment type"),
                "job_function": criteria.get("Job function"),
                "industries": criteria.get("Industries"),
            },
        }

    @staticmethod
    def _parse_criteria(soup: BeautifulSoup) -> dict[str, str]:
        criteria: dict[str, str] = {}
        for item in soup.select(".description__job-criteria-item"):
            key = StephensonHarwoodPlugin._text(item, ".description__job-criteria-subheader")
            value = StephensonHarwoodPlugin._text(item, ".description__job-criteria-text")
            if key and value:
                criteria[key] = value
        return criteria

    @staticmethod
    def _topcard_location(soup: BeautifulSoup) -> str | None:
        flavors = [
            " ".join(item.get_text(" ", strip=True).split())
            for item in soup.select(".topcard__flavor")
        ]
        for value in flavors:
            if value and "stephenson harwood" not in value.lower():
                return value
        return None

    @staticmethod
    def _canonical_job_url(url: str | None) -> str | None:
        if not url:
            return None
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    @staticmethod
    def _job_id_from_card(card, job_url: str | None) -> str | None:
        urn = card.get("data-entity-urn") or ""
        match = re.search(r"jobPosting:(\d+)", urn)
        if match:
            return match.group(1)
        if not job_url:
            return None
        match = re.search(r"-(\d+)$", urlparse(job_url).path)
        return match.group(1) if match else None

    @staticmethod
    def _html_to_text(html: str | None) -> str | None:
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        for element in soup.select("script, style, button"):
            element.decompose()
        text = soup.get_text("\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines) or None

    @staticmethod
    def _text(root, selector: str) -> str | None:
        element = root.select_one(selector)
        if element is None:
            return None
        value = " ".join(element.get_text(" ", strip=True).split())
        return value or None

    @staticmethod
    def _get_with_retry(
        session: requests.Session,
        url: str,
        *,
        timeout: int,
        max_retries: int,
        params: dict[str, Any] | None = None,
    ) -> requests.Response | None:
        for attempt in range(max_retries + 1):
            try:
                response = session.get(url, params=params, timeout=timeout)
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else 2.0 * (attempt + 1)
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                response.encoding = "utf-8"
                return response
            except requests.RequestException:
                if attempt >= max_retries:
                    return None
                time.sleep(1.0 * (attempt + 1))
        return None

    @staticmethod
    def _prepare_response(response: requests.Response) -> None:
        response.raise_for_status()
        response.encoding = "utf-8"
