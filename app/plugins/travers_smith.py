from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class TraversSmithPlugin(BasePlugin):
    plugin_name = "travers_smith"
    display_name = "Travers Smith"
    enabled = True
    careers_url = "https://fsr.cvmailuk.com/traverssmithlateralhires/main.cfm?page=jobBoard&fo=1&groupType_7=&groupType_112=&filter="
    description = "Travers Smith lateral hires CVMail scraper"
    required_config = ["source_url"]
    default_config = {
        "source_url": careers_url,
        "fetch_detail_pages": True,
        "timeout": 30,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = self.plugin_config.get("source_url") or self.careers_url
        timeout = int(self.plugin_config.get("timeout", 30))
        fetch_detail_pages = bool(self.plugin_config.get("fetch_detail_pages", True))

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
        soup = BeautifulSoup(response.text, "html.parser")

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()

        for row in soup.select("tr.odd, tr.even"):
            title_el = row.select_one("a.jobMoreDetailCaptionStyle[href]")
            if title_el is None:
                continue

            title = self._clean_text(title_el.get_text(" ", strip=True))
            href = title_el.get("href") or ""
            job_url = urljoin(source_url, href)
            job_id = self._query_value(job_url, "jobId")
            columns = [
                self._clean_text(cell.get_text(" ", strip=True))
                for cell in row.select("td.jbTableTextStyle")
            ]
            values = [value for value in columns[1:] if value]
            practice_area = values[0] if values else None
            job_category = values[1] if len(values) > 1 else None

            if not title or not job_id or job_id in seen:
                continue
            seen.add(job_id)

            detail = self._fetch_detail(session, job_url, timeout) if fetch_detail_pages else {}
            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": detail.get("title") or title,
                    "office_location": detail.get("location"),
                    "practice_area": detail.get("practice_area") or practice_area,
                    "pqe_level": detail.get("pqe_level"),
                    "description": detail.get("description"),
                    "source_reference": job_id,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "cvmail_html",
                        "job_category": job_category,
                        "closing_date": detail.get("closing_date"),
                        "description_source": "detail_page" if detail.get("description") else "listing_row",
                    },
                }
            )

        return jobs

    def _fetch_detail(self, session: requests.Session, job_url: str, timeout: int) -> dict[str, str | None]:
        try:
            response = session.get(job_url, timeout=timeout)
            self._prepare_response(response)
        except requests.RequestException:
            return {}

        soup = BeautifulSoup(response.text, "html.parser")
        fields = self._detail_fields(soup)
        return {
            "title": fields.get("Job Title"),
            "closing_date": fields.get("Closing Date"),
            "location": fields.get("Location"),
            "practice_area": fields.get("Practice Area/Department"),
            "pqe_level": fields.get("PQE Level"),
            "description": fields.get("Description"),
        }

    @staticmethod
    def _detail_fields(soup: BeautifulSoup) -> dict[str, str]:
        fields: dict[str, str] = {}
        for row in soup.select("tr"):
            label_el = row.select_one(".jobFieldStyle")
            value_el = row.select_one(".jobValueStyle")
            if label_el is None or value_el is None:
                continue
            label = TraversSmithPlugin._clean_text(label_el.get_text(" ", strip=True))
            value = TraversSmithPlugin._clean_text(value_el.get_text("\n", strip=True))
            if label and label.startswith("Description"):
                label = "Description"
            if label and value:
                fields[label] = value
        return fields

    @staticmethod
    def _query_value(url: str, name: str) -> str | None:
        values = parse_qs(urlparse(url).query).get(name)
        return values[0] if values else None

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
