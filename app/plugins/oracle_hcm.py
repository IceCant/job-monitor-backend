from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class OracleHCMPlugin(BasePlugin):
    plugin_name = "oracle_hcm"
    display_name = "Oracle HCM"
    discoverable = False
    enabled = True
    careers_url: str | None = None
    description = "Scraper for Oracle HCM Candidate Experience careers APIs"
    required_config = ["api_url", "careers_url", "site_number"]
    default_config: dict[str, Any] = {
        "api_url": "",
        "careers_url": "",
        "site_number": "",
        "limit": 25,
        "max_pages": 0,
        "sort_by": "POSTING_DATES_DESC",
        "timeout": 60,
    }

    expand = (
        "requisitionList.workLocation,"
        "requisitionList.otherWorkLocations,"
        "requisitionList.secondaryLocations,"
        "flexFieldsFacet.values,"
        "requisitionList.requisitionFlexFields"
    )

    def __init__(self, firm_name: str, plugin_config: dict[str, Any] | None = None, **kwargs: Any):
        super().__init__(firm_name=firm_name, plugin_config=plugin_config, **kwargs)
        cfg = {**self.default_config, **(plugin_config or {}), **kwargs}
        self.api_url = _optional_str(cfg.get("api_url"))
        self.careers_url = _optional_str(cfg.get("careers_url") or self.careers_url)
        self.site_number = _optional_str(cfg.get("site_number"))
        self.limit = int(cfg.get("limit") or 25)
        self.max_pages = int(cfg.get("max_pages") or 0)
        self.sort_by = _optional_str(cfg.get("sort_by")) or "POSTING_DATES_DESC"
        self.timeout = int(cfg.get("timeout") or 60)

        if not self.api_url or not self.careers_url or not self.site_number:
            raise ValueError("Oracle HCM plugin requires api_url, careers_url, and site_number")

    async def scrape(self) -> list[dict[str, Any]]:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Referer": self.careers_url,
            }
        )

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        offset = 0
        page = 0
        total_expected: int | None = None

        while True:
            if self.max_pages > 0 and page >= self.max_pages:
                break
            if total_expected is not None and offset >= total_expected:
                break

            data = self._fetch_page(session, offset)
            search = (data.get("items") or [{}])[0]
            total_expected = self._total_count(search, total_expected)
            requisitions = search.get("requisitionList") or []
            if not requisitions:
                break

            new_on_page = 0
            for req in requisitions:
                reference = _optional_str(req.get("Id"))
                title = _optional_str(req.get("Title"))
                if not reference or not title or reference in seen:
                    continue

                seen.add(reference)
                new_on_page += 1
                locations = self._locations(req)
                jobs.append(
                    {
                        "job_url": self._job_url(reference),
                        "firm_name": self.firm_name,
                        "title": title,
                        "office_location": "; ".join(locations) if locations else _optional_str(req.get("PrimaryLocation")),
                        "practice_area": _optional_str(req.get("JobFamily") or req.get("JobFunction")),
                        "pqe_level": None,
                        "description": self._description(req),
                        "source_reference": reference,
                        "status": "LIVE",
                        "extra_info": {
                            "source": "oracle_hcm_candidate_experience",
                            "job_id": reference,
                            "posted_date": _optional_str(req.get("PostedDate")),
                            "posting_end_date": _optional_str(req.get("PostingEndDate")),
                            "primary_location": _optional_str(req.get("PrimaryLocation")),
                            "locations": locations,
                            "worker_type": _optional_str(req.get("WorkerType")),
                            "contract_type": _optional_str(req.get("ContractType")),
                            "workplace_type": _optional_str(req.get("WorkplaceType")),
                            "listing_page": page + 1,
                        },
                    }
                )

            if new_on_page == 0:
                break
            offset += self.limit
            page += 1

        return jobs

    def _fetch_page(self, session: requests.Session, offset: int) -> dict[str, Any]:
        response = session.get(
            self.api_url,
            params={
                "onlyData": "true",
                "expand": self.expand,
                "finder": (
                    f"findReqs;siteNumber={self.site_number},"
                    f"limit={self.limit},"
                    f"offset={offset},"
                    f"sortBy={self.sort_by}"
                ),
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def _job_url(self, reference: str) -> str:
        base = self.careers_url.split("?", 1)[0].rstrip("/")
        if base.endswith("/jobs"):
            base = base.rsplit("/", 1)[0]
        return f"{base}/job/{reference}"

    @staticmethod
    def _total_count(search: dict[str, Any], fallback: int | None) -> int | None:
        value = search.get("TotalJobsCount")
        try:
            total = int(value)
        except (TypeError, ValueError):
            return fallback
        return total if total >= 0 else fallback

    @classmethod
    def _locations(cls, req: dict[str, Any]) -> list[str]:
        values: list[str] = []
        cls._append_location(values, req.get("PrimaryLocation"))

        for item in req.get("secondaryLocations") or []:
            cls._append_location(values, item.get("Name"))
        for item in req.get("workLocation") or []:
            cls._append_location(values, item.get("TownOrCity") or item.get("LocationName"))
        for item in req.get("otherWorkLocations") or []:
            cls._append_location(values, item.get("TownOrCity") or item.get("LocationName"))

        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = value.split(",", 1)[0].strip().casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(value)
        return deduped

    @classmethod
    def _append_location(cls, values: list[str], value: Any) -> None:
        text = _optional_str(value)
        if text:
            values.append(cls._clean_location(text))

    @staticmethod
    def _clean_location(value: str) -> str:
        text = " ".join(value.split())
        if "," in text:
            city, rest = text.split(",", 1)
            return f"{city.title()}, {rest.strip()}"
        return text.title() if text.isupper() else text

    @classmethod
    def _description(cls, req: dict[str, Any]) -> str | None:
        parts = [
            req.get("ShortDescriptionStr"),
            req.get("ExternalResponsibilitiesStr"),
            req.get("ExternalQualificationsStr"),
        ]
        cleaned = [text for part in parts if (text := cls._html_to_text(part))]
        return "\n\n".join(cleaned) if cleaned else None

    @staticmethod
    def _html_to_text(value: Any) -> str | None:
        text = _optional_str(value)
        if not text:
            return None
        soup = BeautifulSoup(text, "html.parser")
        extracted = soup.get_text("\n", strip=True)
        lines = [line.strip() for line in extracted.splitlines() if line.strip()]
        return "\n".join(lines) or None
