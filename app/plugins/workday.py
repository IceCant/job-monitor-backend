# app/plugins/workday.py

from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin
from app.schemas.job_result import JobResult


def _to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return str(value)


def _to_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


class WorkdayPlugin(BasePlugin):
    plugin_name = "workday"
    display_name = "NRF Workday"
    enabled = True
    careers_url = "https://nrf.wd3.myworkdayjobs.com/External"
    description = "Scraper for Workday-powered careers APIs"
    required_config = ["api_url", "careers_url"]
    default_config = {
        "api_url": "https://nrf.wd3.myworkdayjobs.com/wday/cxs/nrf/External/jobs",
        "max_pages": 0,
        "fetch_detail_pages": False,
        "request_timeout": 60,
        "detail_timeout": 20,
    }

    def __init__(
        self,
        firm_name: str,
        plugin_config: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        super().__init__(firm_name=firm_name, plugin_config=plugin_config, **kwargs)
        cfg = self.plugin_config
        # Allow either plugin_config values or direct kwargs for flexibility.
        api_url = _to_optional_str(kwargs.get("api_url") or cfg.get("api_url"))
        careers_url = _to_optional_str(kwargs.get("careers_url") or cfg.get("careers_url"))
        self.max_pages = _to_optional_int(kwargs.get("max_pages", cfg.get("max_pages")))
        self.fetch_detail_pages = bool(kwargs.get("fetch_detail_pages", cfg.get("fetch_detail_pages", False)))
        self.progress_callback = kwargs.get("progress_callback")
        self.request_timeout = _to_optional_int(kwargs.get("request_timeout", cfg.get("request_timeout"))) or 60
        self.detail_timeout = _to_optional_int(kwargs.get("detail_timeout", cfg.get("detail_timeout"))) or 20

        if not api_url or not careers_url:
            raise ValueError("Workday plugin requires api_url and careers_url")

        self.api_url: str = api_url
        self.careers_url: str = careers_url

    async def scrape(self):

        all_jobs = []
        session = requests.Session()

        offset = 0
        limit = 20
        page = 0
        total_expected: int | None = None
        seen_jobs: set[str] = set()

        self._emit_progress(15, "Starting", "Starting Workday scrape...", 0)

        while True:

            if self.max_pages != 0 and self.max_pages is not None and page >= self.max_pages:
                break
            if total_expected is not None and offset >= total_expected:
                break

            payload = {
                "limit": limit,
                "offset": offset,
                "searchText": ""
            }

            api_url = str(self.api_url)
            self._emit_progress(
                self._page_percent(page, total_expected),
                "Loading page",
                f"Loading Workday page {page + 1}...",
                len(all_jobs),
            )

            response = session.post(
                api_url,
                json=payload,
                timeout=self.request_timeout
            )

            response.raise_for_status()
            data = response.json()
            reported_total = self._expected_total(data)
            if reported_total is not None:
                total_expected = reported_total

            jobs = data.get("jobPostings", [])

            if not jobs:
                break
            if total_expected is not None:
                jobs = jobs[: max(total_expected - offset, 0)]
            if not jobs:
                break

            new_jobs_on_page = 0
            for job_index, job in enumerate(jobs):
                bullet_fields = job.get("bulletFields", []) or []
                reference = bullet_fields[0] if bullet_fields else None
                external_path = job.get("externalPath")
                job_key = self._job_key(job)
                if job_key in seen_jobs:
                    continue
                seen_jobs.add(job_key)
                new_jobs_on_page += 1
                if self.fetch_detail_pages:
                    processed = min(offset + job_index, total_expected or offset + len(jobs))
                    self._emit_progress(
                        self._detail_percent(processed, total_expected),
                        "Fetching details",
                        self._detail_message(processed + 1, total_expected),
                        len(all_jobs),
                    )
                detail = self._fetch_detail(session, external_path) if self.fetch_detail_pages else {}
                info = detail.get("jobPostingInfo") or {}
                description = (
                    self._html_to_text(info.get("jobDescription"))
                    or self._html_to_text(job.get("description"))
                )

                all_jobs.append(
                    JobResult(
                        job_url=(
                            self.careers_url
                            + job.get("externalPath", "")
                        ),
                        firm_name=self.firm_name,
                        title=info.get("title") or job.get("title"),
                        office_location=job.get(
                            "locationsText",
                            ""
                        ),
                        practice_area=None,
                        pqe_level=None,
                        description=description,
                        source_reference=reference,
                        status="LIVE",
                        extra_info={
                            "title": info.get("title") or job.get("title"),
                            "job_id": reference,
                            "bullet_fields": bullet_fields,
                            "posted_on": job.get("postedOn"),
                            "start_date": info.get("startDate"),
                            "description_source": "job_detail" if description else "search_result",
                        }
                    )
                )
                self._emit_progress(
                    self._detail_percent(min(len(all_jobs), total_expected or len(all_jobs)), total_expected),
                    "Parsing jobs",
                    f"Parsed {len(all_jobs)} job{'' if len(all_jobs) == 1 else 's'}...",
                    len(all_jobs),
                )

            if new_jobs_on_page == 0:
                break
            offset += limit
            page += 1

        self._emit_progress(70, "Scrape complete", f"Fetched {len(all_jobs)} jobs. Preparing to save...", len(all_jobs))
        return all_jobs

    def _fetch_detail(self, session: requests.Session, external_path: str | None) -> dict[str, Any]:
        if not external_path:
            return {}

        detail_base_url = self.api_url.rsplit("/jobs", 1)[0]
        detail_url = urljoin(f"{detail_base_url}/", external_path.lstrip("/"))
        try:
            response = session.get(detail_url, timeout=self.detail_timeout)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            return {}

    @staticmethod
    def _html_to_text(html: str | None) -> str | None:
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines) or None

    @staticmethod
    def _expected_total(data: dict[str, Any]) -> int | None:
        total = data.get("total")
        try:
            total_int = int(total)
        except (TypeError, ValueError):
            return None
        if total_int <= 0:
            return None
        return total_int

    def _page_percent(self, page: int, total_expected: int | None) -> int:
        if self.max_pages:
            return 15 + min(10, round((page / max(self.max_pages, 1)) * 10))
        if total_expected:
            return 15 + min(10, round(((page * 20) / total_expected) * 10))
        return 15

    @staticmethod
    def _detail_percent(processed: int, total_expected: int | None) -> int:
        if not total_expected:
            return 25
        capped_processed = min(processed, total_expected)
        return 25 + min(45, round((capped_processed / max(total_expected, 1)) * 45))

    @staticmethod
    def _detail_message(processed: int, total_expected: int | None) -> str:
        if total_expected:
            capped_processed = min(processed, total_expected)
            return f"Fetching details {capped_processed}/{total_expected}..."
        return f"Fetching details {processed}..."

    @staticmethod
    def _job_key(job: dict[str, Any]) -> str:
        bullet_fields = job.get("bulletFields", []) or []
        reference = bullet_fields[0] if bullet_fields else None
        external_path = job.get("externalPath")
        return str(external_path or reference or f"{job.get('title')}|{job.get('locationsText')}")

    def _emit_progress(self, percent: int, stage: str, message: str, jobs_seen: int) -> None:
        callback = self.progress_callback
        if not callable(callback):
            return
        callback(
            {
                "current_firm_percent": percent,
                "current_firm_stage": stage,
                "message": message,
                "jobs_seen": jobs_seen,
            }
        )
