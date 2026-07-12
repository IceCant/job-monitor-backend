from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

import requests

from app.plugins.base import BasePlugin
from app.plugins.helper.helper import html_to_text


class BrowneJacobsonPlugin(BasePlugin):
    plugin_name = "browne_jacobson"
    display_name = "Browne Jacobson"
    enabled = True
    careers_url = "https://brownejacobsoncareers.com/VacancyPosting/Search#!/"
    description = "Browne Jacobson GTI/Solr careers scraper"
    required_config = ["source_url", "api_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "api_url": "https://brownejacobsoncareers.com/Search/CandidateVacancies",
        "page_size": 100,
        "max_pages": 0,
        "timeout": 60,
    }

    _FIELD_LIST = ",".join(
        [
            "dbid",
            "title",
            "dynamicstring_ShortName",
            "dynamicstring_Vacancy_SearchId",
            "dynamicstring_VacancyDetail_Referencenumber_Text",
            "dynamicstring_VacancyDetail_Jobtitle_Text",
            "dynamicstring_VacancyDetail_Description_Text",
            "dynamicstring_VacancyDetail_Location_Text",
            "dynamicstring_VacancyDetail_Businessarea_Text",
            "dynamicstring_VacancyDetail_Level_Text",
            "dynamicstring_VacancyDetail_Duration_Text",
            "dynamicstring_VacancyDetail_DurationDetails_Text",
            "dynamicstring_VacancyDetail_Hours_Text",
            "dynamicstring_Vacancy_FrameworkName",
            "dynamicstring_VacancyDetail_Team_Text",
            "dynamicstring_Vacancy_PostingStatus",
            "dynamicdate_VacancyPosting_ScheduledOpenDate",
            "dynamicdate_VacancyPosting_ScheduledCloseDate",
            "dynamicmultistrings_Details",
        ]
    )

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = str(self.plugin_config.get("source_url") or self.careers_url)
        api_url = str(self.plugin_config.get("api_url") or "").strip()
        page_size = max(1, min(int(self.plugin_config.get("page_size", 100)), 1000))
        max_pages = int(self.plugin_config.get("max_pages", 0))
        timeout = int(self.plugin_config.get("timeout", 60))
        if not api_url:
            raise ValueError("Browne Jacobson API configuration is incomplete")

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Referer": source_url,
            }
        )

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        start = 0
        page = 1
        total: int | None = None

        while True:
            if max_pages > 0 and page > max_pages:
                break

            response = session.get(
                api_url,
                params={
                    "q": "*:*",
                    "wt": "json",
                    "rows": page_size,
                    "start": start,
                    "fl": self._FIELD_LIST,
                },
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            container = payload.get("response") if isinstance(payload, dict) else None
            if not isinstance(container, dict):
                break

            docs = container.get("docs") or []
            if not isinstance(docs, list) or not docs:
                break
            total = total or self._safe_int(container.get("numFound"))

            new_on_page = self._append_jobs(docs, jobs, seen, source_url, page)
            if new_on_page == 0:
                break
            start += len(docs)
            if len(docs) < page_size:
                break
            if total is not None and start >= total:
                break
            page += 1

        if not jobs:
            raise ValueError("Browne Jacobson API returned no jobs")
        return jobs

    def _append_jobs(
        self,
        docs: list[Any],
        jobs: list[dict[str, Any]],
        seen: set[str],
        source_url: str,
        page: int,
    ) -> int:
        new_on_page = 0
        for doc in docs:
            if not isinstance(doc, dict):
                continue

            dbid = self._clean(doc.get("dbid"))
            reference = self._clean(
                doc.get("dynamicstring_Vacancy_SearchId")
                or doc.get("dynamicstring_VacancyDetail_Referencenumber_Text")
                or dbid
            )
            title = self._clean(doc.get("dynamicstring_VacancyDetail_Jobtitle_Text")) or self._clean(
                doc.get("title")
            )
            if not reference or not title or reference in seen:
                continue

            description = self._description(doc.get("dynamicstring_VacancyDetail_Description_Text"))
            seen.add(reference)
            new_on_page += 1
            jobs.append(
                {
                    "job_url": self._job_url(doc, source_url),
                    "firm_name": self.firm_name,
                    "title": title,
                    "office_location": self._clean(
                        doc.get("dynamicstring_VacancyDetail_Location_Text")
                    ),
                    "practice_area": self._clean(
                        doc.get("dynamicstring_VacancyDetail_Businessarea_Text")
                    ),
                    "pqe_level": self._clean(doc.get("dynamicstring_VacancyDetail_Level_Text")),
                    "description": description,
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "browne_jacobson_solr_api",
                        "listing_page": page,
                        "dbid": dbid,
                        "reference_number": self._clean(
                            doc.get("dynamicstring_VacancyDetail_Referencenumber_Text")
                        ),
                        "scheduled_open_date": self._clean(
                            doc.get("dynamicdate_VacancyPosting_ScheduledOpenDate")
                        ),
                        "scheduled_close_date": self._clean(
                            doc.get("dynamicdate_VacancyPosting_ScheduledCloseDate")
                        ),
                        "duration": self._clean(
                            doc.get("dynamicstring_VacancyDetail_Duration_Text")
                        ),
                        "duration_details": self._clean(
                            doc.get("dynamicstring_VacancyDetail_DurationDetails_Text")
                        ),
                        "hours": self._clean(doc.get("dynamicstring_VacancyDetail_Hours_Text")),
                        "framework": self._clean(doc.get("dynamicstring_Vacancy_FrameworkName")),
                        "team": self._clean(doc.get("dynamicstring_VacancyDetail_Team_Text")),
                        "posting_status": self._clean(
                            doc.get("dynamicstring_Vacancy_PostingStatus")
                        ),
                        "details": self._values(doc.get("dynamicmultistrings_Details")),
                    },
                }
            )
        return new_on_page

    @classmethod
    def _job_url(cls, doc: dict[str, Any], source_url: str) -> str:
        dbid = cls._clean(doc.get("dbid"))
        short_name = cls._slug(cls._clean(doc.get("dynamicstring_ShortName")))
        if dbid and short_name:
            return urljoin(source_url, f"/{short_name}/{dbid}/viewdetails")
        return source_url

    @classmethod
    def _values(cls, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        cleaned: list[str] = []
        for value in values:
            text = cls._clean(value)
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned

    @classmethod
    def _description(cls, value: Any) -> str | None:
        text = cls._clean(value)
        if not text:
            return None
        if "<" in text or "&lt;" in text:
            return html_to_text(text)
        return text

    @staticmethod
    def _slug(value: str | None) -> str | None:
        if not value:
            return None
        slug = re.sub(r"[^a-z0-9-]+", "-", value.casefold()).strip("-")
        return slug or None

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        if text.casefold() in {"(empty)", "empty", "not specified"}:
            return None
        return text or None
