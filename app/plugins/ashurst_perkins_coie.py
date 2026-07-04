from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class AshurstPerkinsCoiePlugin(BasePlugin):
    plugin_name = "ashurst_perkins_coie"
    display_name = "Ashurst Perkins Coie"
    enabled = True
    careers_url = "https://fsr.cvmailuk.com/ashurstperkinscoiecareers/main.cfm?srxksl=1"
    description = "Ashurst Perkins Coie CVMail careers scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "fetch_detail_pages": False,
        "max_pages": 0,
        "timeout": 30,
        "detail_timeout": 8,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = str(self.plugin_config.get("source_url") or self.careers_url)
        source_url = self._ensure_scheme(source_url)
        timeout = int(self.plugin_config.get("timeout", 30))
        detail_timeout = int(self.plugin_config.get("detail_timeout", 8))
        fetch_detail_pages = bool(self.plugin_config.get("fetch_detail_pages", False))
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

        while True:
            soup = BeautifulSoup(response.text, "lxml")
            before = len(jobs)
            self._append_jobs(
                soup,
                source_url,
                session,
                detail_timeout,
                fetch_detail_pages,
                page,
                jobs,
                seen,
            )
            if len(jobs) == before:
                break
            if max_pages > 0 and page >= max_pages:
                break

            next_response = self._fetch_next_page(session, soup, response.url, timeout)
            if next_response is None:
                break

            response = next_response
            page += 1

        return jobs

    def _append_jobs(
        self,
        soup: BeautifulSoup,
        source_url: str,
        session: requests.Session,
        detail_timeout: int,
        fetch_detail_pages: bool,
        page: int,
        jobs: list[dict[str, Any]],
        seen: set[str],
    ) -> None:
        for row in soup.select("table.cvmJobBoardHeader tr.odd, table.cvmJobBoardHeader tr.even"):
            title_el = row.select_one("a.jobMoreDetailCaptionStyle[href]")
            if title_el is None:
                continue

            title = self._clean_text(title_el.get_text(" ", strip=True))
            href = str(title_el.get("href") or "")
            raw_job_url = urljoin(source_url, href)
            job_id = self._query_value(raw_job_url, "jobId")
            if not title or not job_id or job_id in seen:
                continue

            cells = [self._clean_text(cell.get_text(" ", strip=True)) for cell in row.select("td.jbTableTextStyle")]
            listing_location = cells[-1] if len(cells) > 1 else None
            job_url = self._canonical_job_url(source_url, href)
            detail = self._fetch_detail(session, raw_job_url, detail_timeout) if fetch_detail_pages else {}

            seen.add(job_id)
            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": detail.get("title") or title,
                    "office_location": detail.get("location") or listing_location,
                    "practice_area": detail.get("practice_area"),
                    "pqe_level": detail.get("pqe_level"),
                    "description": detail.get("description"),
                    "source_reference": job_id,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "ashurst_perkins_coie_cvmail_html",
                        "source_detail_url": job_url,
                        "listing_page": page,
                        "listing_location": listing_location,
                        "closing_date": detail.get("closing_date"),
                        "description_source": "detail_page" if detail.get("description") else "listing_row",
                    },
                }
            )

    def _fetch_detail(self, session: requests.Session, job_url: str, timeout: int) -> dict[str, str | None]:
        try:
            response = session.get(job_url, timeout=timeout)
            self._prepare_response(response)
        except requests.RequestException:
            return {}

        soup = BeautifulSoup(response.text, "lxml")
        fields = self._detail_fields(soup)
        return {
            "title": fields.get("Job Title"),
            "closing_date": fields.get("Closing Date"),
            "location": fields.get("Location"),
            "practice_area": fields.get("Practice Area/Department"),
            "pqe_level": fields.get("PQE Level"),
            "description": fields.get("Description"),
        }

    def _fetch_next_page(
        self,
        session: requests.Session,
        soup: BeautifulSoup,
        current_url: str,
        timeout: int,
    ) -> requests.Response | None:
        form = soup.select_one('form[name="paging"]')
        next_button = form.select_one('input[name="next_page"]:not([disabled])') if form else None
        if form is None or next_button is None:
            return None

        action = urljoin(current_url, str(form.get("action") or current_url))
        data: dict[str, str] = {}
        for element in form.select("input"):
            name = str(element.get("name") or "").strip()
            input_type = str(element.get("type") or "").lower()
            if not name or input_type in {"submit", "image", "button"}:
                continue
            data[name] = str(element.get("value") or "")
        data["next_page"] = str(next_button.get("value") or "Next >>")

        response = session.post(action, data=data, timeout=timeout)
        self._prepare_response(response)
        return response

    @classmethod
    def _detail_fields(cls, soup: BeautifulSoup) -> dict[str, str]:
        fields: dict[str, str] = {}
        for row in soup.select("tr"):
            label_el = row.select_one(".jobFieldStyle")
            value_el = row.select_one(".jobValueStyle")
            if label_el is None or value_el is None:
                continue

            label = cls._clean_text(label_el.get_text(" ", strip=True))
            value = cls._clean_text(value_el.get_text("\n", strip=True))
            if label and label.startswith("Description"):
                label = "Description"
            if label and value:
                fields[label] = value
        return fields

    @classmethod
    def _canonical_job_url(cls, source_url: str, href: str) -> str:
        absolute = urljoin(source_url, href)
        parsed = urlparse(absolute)
        query = parse_qs(parsed.query)
        job_id = cls._query_value(absolute, "jobId")
        if not job_id:
            return urlunparse(parsed._replace(query=urlencode(cls._stable_query(query), doseq=True)))

        stable_query: dict[str, str] = {
            "page": "jobSpecific",
            "jobId": job_id,
        }
        srxksl = cls._query_value(absolute, "srxksl") or cls._query_value(source_url, "srxksl")
        if srxksl:
            stable_query["srxksl"] = srxksl
        return urlunparse(parsed._replace(query=urlencode(stable_query)))

    @staticmethod
    def _stable_query(query: dict[str, list[str]]) -> dict[str, list[str]]:
        volatile_keys = {"rcd", "queryString", "x-token"}
        return {key: values for key, values in query.items() if key not in volatile_keys}

    @staticmethod
    def _query_value(url: str, name: str) -> str | None:
        values = parse_qs(urlparse(url).query).get(name)
        if not values:
            return None
        value = str(values[0]).strip()
        return value or None

    @staticmethod
    def _clean_text(value: str | None) -> str | None:
        if not value:
            return None
        text = " ".join(value.split())
        return text or None

    @staticmethod
    def _prepare_response(response: requests.Response) -> None:
        response.raise_for_status()
        response.encoding = "utf-8"

    @staticmethod
    def _ensure_scheme(url: str) -> str:
        value = url.strip()
        if value.startswith(("http://", "https://")):
            return value
        return f"https://{value}"
