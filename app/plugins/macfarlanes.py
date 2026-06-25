import json
import re
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class MacfarlanesPlugin(BasePlugin):
    plugin_name = "macfarlanes"
    display_name = "Macfarlanes"
    enabled = True
    careers_url = "https://www.macfarlanes.com/join-us/vacancies/?type%5B0%5D=Vacancy"
    description = "Macfarlanes public vacancies scraper"
    required_config = ["source_url"]
    default_config = {
        "source_url": careers_url,
        "algolia_url": "https://m4urjc02kx-1.algolianet.com/1/indexes/*/queries",
        "algolia_application_id": "M4URJC02KX",
        "algolia_api_key": "403fd3194fb7199f6198168d9feb9624",
        "algolia_index": "Production_main",
        "hits_per_page": 12,
        "max_pages": 5,
        "use_algolia": True,
        "external_board_url": "https://macfarlanes.current-vacancies.com/Website/Search",
        "scrape_external_board": False,
        "include_unlinked_featured": False,
        "allowed_client_ids": [],
        "default_location": "London",
        "timeout": 30,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = self.plugin_config.get("source_url") or self.careers_url
        timeout = int(self.plugin_config.get("timeout", 30))

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

        if self.plugin_config.get("use_algolia", True):
            self._extend_jobs(jobs, seen, self._scrape_algolia(session, timeout))

        response = session.get(source_url, timeout=timeout)
        self._prepare_response(response)
        self._extend_jobs(jobs, seen, self._parse_public_page(response.text, source_url))

        if self.plugin_config.get("scrape_external_board"):
            external_board_url = self.plugin_config.get("external_board_url")
            if external_board_url:
                response = session.get(external_board_url, timeout=timeout)
                self._prepare_response(response)
                self._extend_jobs(
                    jobs,
                    seen,
                    self._parse_networx_page(response.text, external_board_url),
                )

        return jobs

    def _scrape_algolia(
        self,
        session: requests.Session,
        timeout: int,
    ) -> list[dict[str, Any]]:
        algolia_url = self.plugin_config.get("algolia_url") or self.default_config["algolia_url"]
        hits_per_page = int(self.plugin_config.get("hits_per_page", 12))
        max_pages = int(self.plugin_config.get("max_pages", 5))
        jobs: list[dict[str, Any]] = []

        for page in range(max_pages):
            response = session.post(
                algolia_url,
                params={
                    "x-algolia-agent": (
                        "Algolia for JavaScript (5.51.0); Lite (5.51.0); "
                        "Browser; instantsearch.js (4.94.0)"
                    ),
                    "x-algolia-api-key": self.plugin_config.get("algolia_api_key"),
                    "x-algolia-application-id": self.plugin_config.get("algolia_application_id"),
                },
                data=json.dumps(self._algolia_payload(page, hits_per_page)),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "text/plain",
                    "Origin": "https://www.macfarlanes.com",
                    "Referer": "https://www.macfarlanes.com/",
                },
                timeout=timeout,
            )
            self._prepare_response(response)

            data = response.json()
            result = (data.get("results") or [{}])[0]
            hits = result.get("hits") or []
            for hit in hits:
                job = self._job_from_algolia_hit(hit)
                if job:
                    jobs.append(job)

            if not hits or page + 1 >= int(result.get("nbPages") or 0):
                break

        return jobs

    def _algolia_payload(self, page: int, hits_per_page: int) -> dict[str, Any]:
        common = {
            "indexName": self.plugin_config.get("algolia_index") or "Production_main",
            "analyticsTags": ["web_desktop"],
            "filters": '(contentTypeFacet:"Vacancy")',
            "highlightPostTag": "__/ais-highlight__",
            "highlightPreTag": "__ais-highlight__",
            "hitsPerPage": hits_per_page,
            "ignorePlurals": True,
            "maxValuesPerFacet": 100,
            "page": page,
            "query": "",
            "removeStopWords": True,
            "userToken": "anonymous-job-monitor",
        }
        return {
            "requests": [
                {
                    **common,
                    "clickAnalytics": True,
                    "facetFilters": [["contentTypeFacet:Vacancy"]],
                    "facets": ["authors", "contentTypeFacet", "filters.roleType", "related"],
                },
                {
                    **common,
                    "analytics": False,
                    "clickAnalytics": False,
                    "facets": "contentTypeFacet",
                    "hitsPerPage": 0,
                },
            ]
        }

    def _job_from_algolia_hit(self, hit: dict[str, Any]) -> dict[str, Any] | None:
        tile = hit.get("searchTile") or {}
        link = tile.get("link") or {}
        job_url = link.get("url")
        title = self._clean_text(tile.get("heading"))
        reference = hit.get("objectID") or tile.get("originId")

        if not job_url or not title or not reference:
            return None

        role_types = (hit.get("filters") or {}).get("roleType") or []
        if not isinstance(role_types, list):
            role_types = [role_types]

        return self._job(
            job_url=job_url,
            title=title,
            source_reference=str(reference),
            practice_area=", ".join(str(item) for item in role_types if item) or None,
            description=self._description_from_algolia_content(hit.get("content"), title),
            extra_info={
                "source": "algolia",
                "object_id": hit.get("objectID"),
                "origin_id": tile.get("originId") or hit.get("originId"),
                "published_date": tile.get("publishedDate"),
                "role_type": role_types,
                "tags": tile.get("tags") or [],
            },
        )

    def _parse_public_page(self, html: str, source_url: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[dict[str, Any]] = []

        for anchor in soup.select("a[href]"):
            title = self._clean_text(anchor.get_text(" ", strip=True))
            href = (anchor.get("href") or "").strip()
            job_url = urljoin(source_url, href)

            if not self._looks_like_vacancy_link(job_url, title):
                continue

            container = self._nearest_content_container(anchor)
            description = self._clean_text(container.get_text(" ", strip=True)) if container else None

            jobs.append(
                self._job(
                    job_url=job_url,
                    title=title,
                    source_reference=self._reference_from_url(job_url),
                    description=description,
                    extra_info={"source": "macfarlanes_public_page"},
                )
            )

        for item in self._extract_featured_vacancies(html, source_url):
            jobs.append(item)

        return jobs

    def _parse_networx_page(self, html: str, source_url: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[dict[str, Any]] = []

        for advert in soup.select(".row.advert article.item, article.item"):
            title_el = advert.select_one("a.title[href]")
            if title_el is None:
                continue

            title = self._clean_text(title_el.get_text(" ", strip=True))
            job_url = urljoin(source_url, title_el.get("href") or "")
            client_id = self._query_value(job_url, "cid")
            context = self._clean_text(advert.get_text(" ", strip=True)) or ""

            if not self._is_allowed_networx_job(client_id, context):
                continue

            facts = self._parse_networx_facts(advert)
            reference = facts.get("Reference") or self._reference_from_url(job_url)
            description = self._clean_text(self._first_detail_paragraph(advert))

            jobs.append(
                self._job(
                    job_url=job_url,
                    title=title,
                    source_reference=reference,
                    office_location=facts.get("Location"),
                    description=description,
                    extra_info={
                        "source": "networx_html",
                        "client_id": client_id,
                        "salary": facts.get("Salary"),
                        "closing_date": facts.get("Closing Date"),
                    },
                )
            )

        return jobs

    def _extract_featured_vacancies(self, html: str, source_url: str) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        for match in re.finditer(r"&quot;label&quot;:\[0,&quot;Featured vacancy&quot;\](.{0,2500})", html):
            chunk = match.group(1)
            title = self._html_unescape_match(chunk, r"&quot;heading&quot;:\[0,&quot;(.*?)&quot;\]")
            description = self._html_unescape_match(chunk, r"&quot;text&quot;:\[0,&quot;(.*?)&quot;\]")
            link = self._html_unescape_match(chunk, r"&quot;url&quot;:\[0,&quot;(.*?)&quot;\]")

            if not title or not link:
                continue

            job_url = urljoin(source_url, link)
            source_url_missing = False
            if not self._looks_like_vacancy_link(job_url, title):
                if not self.plugin_config.get("include_unlinked_featured", True):
                    continue
                if "lawyer" not in title.lower() and "associate" not in title.lower():
                    continue
                job_url = source_url
                source_url_missing = True

            if not self._looks_like_vacancy_title(title):
                continue

            jobs.append(
                self._job(
                    job_url=job_url,
                    title=title,
                    source_reference=f"featured:{self._slugify(title)}",
                    description=description,
                    extra_info={
                        "source": "macfarlanes_featured_vacancy",
                        "source_url_missing": source_url_missing,
                    },
                )
            )

        return jobs

    def _job(
        self,
        *,
        job_url: str,
        title: str,
        source_reference: str,
        office_location: str | None = None,
        practice_area: str | None = None,
        description: str | None = None,
        extra_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "job_url": job_url,
            "firm_name": self.firm_name,
            "title": title,
            "office_location": office_location or self.plugin_config.get("default_location") or "London",
            "practice_area": practice_area,
            "pqe_level": None,
            "description": description,
            "source_reference": source_reference,
            "status": "LIVE",
            "extra_info": extra_info or {},
        }

    def _looks_like_vacancy_link(self, job_url: str, title: str | None) -> bool:
        if not title:
            return False

        parsed = urlparse(job_url)
        if parsed.path in {"", "/"}:
            return False

        lowered_url = job_url.lower()
        lowered_title = title.lower()

        if "oneaccount/account/logintype" in lowered_url or "job-alert" in lowered_url:
            return False

        normalized_path = parsed.path.rstrip("/")
        if normalized_path in {"/join-us/lawyers", "/join-us/vacancies"}:
            return False

        if "macfarlanes.com/join-us/vacancies" in lowered_url and parsed.query:
            return False

        vacancy_markers = (
            "/jobs/advert/",
            "/join-us/vacancies/",
            "current-vacancies.com",
            "vacancy",
        )
        title_markers = ("associate", "knowledge lawyer")
        return any(marker in lowered_url for marker in vacancy_markers) or any(
            marker in lowered_title for marker in title_markers
        )

    @staticmethod
    def _looks_like_vacancy_title(title: str) -> bool:
        lowered = title.lower()
        return any(marker in lowered for marker in ("associate", "lawyer", "counsel", "paralegal"))

    def _is_allowed_networx_job(self, client_id: str | None, context: str) -> bool:
        allowed_client_ids = {
            str(item).strip()
            for item in self.plugin_config.get("allowed_client_ids", [])
            if str(item).strip()
        }
        if allowed_client_ids:
            return bool(client_id and client_id in allowed_client_ids)
        return "macfarlanes" in context.lower()

    @staticmethod
    def _extend_jobs(
        jobs: list[dict[str, Any]],
        seen: set[str],
        candidates: list[dict[str, Any]],
    ) -> None:
        for job in candidates:
            reference = job.get("source_reference") or job.get("job_url")
            if not reference or reference in seen:
                continue
            seen.add(reference)
            jobs.append(job)

    @staticmethod
    def _parse_networx_facts(advert) -> dict[str, str]:
        facts: dict[str, str] = {}
        for paragraph in advert.select(".aFurtherInfo p"):
            text = " ".join(paragraph.get_text(" ", strip=True).split())
            if ":" not in text:
                continue
            key, value = text.split(":", 1)
            facts[key.strip()] = value.strip()
        return facts

    @staticmethod
    def _first_detail_paragraph(advert) -> str | None:
        detail = advert.select_one("section.details > p")
        if detail is None:
            return None
        return detail.get_text("\n", strip=True)

    @staticmethod
    def _nearest_content_container(anchor):
        for parent in anchor.parents:
            name = getattr(parent, "name", None)
            if name in {"article", "li", "section", "div"}:
                return parent
        return None

    @staticmethod
    def _reference_from_url(job_url: str) -> str:
        parsed = urlparse(job_url)
        match = re.search(r"/Jobs/Advert/(\d+)", parsed.path, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        slug = parsed.path.strip("/").replace("/", ":")
        return slug or job_url

    @staticmethod
    def _slugify(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

    @staticmethod
    def _query_value(url: str, name: str) -> str | None:
        values = parse_qs(urlparse(url).query).get(name)
        return values[0] if values else None

    @staticmethod
    def _html_unescape_match(text: str, pattern: str) -> str | None:
        match = re.search(pattern, text, flags=re.DOTALL)
        if not match:
            return None
        value = match.group(1)
        return (
            value.replace("&amp;", "&")
            .replace("&quot;", '"')
            .replace("&#x27;", "'")
            .replace("\\/", "/")
            .strip()
        )

    @staticmethod
    def _clean_text(value: str | None) -> str | None:
        if not value:
            return None
        text = " ".join(value.split())
        return text or None

    @staticmethod
    def _description_from_algolia_content(content: str | None, title: str) -> str | None:
        if not content:
            return None

        text = " ".join(content.split())
        lowered = text.lower()
        title_lower = title.lower().strip()

        start = lowered.find("apply for role")
        if start > -1:
            start += len("apply for role")
        else:
            start = lowered.find(title_lower)
            if start > -1:
                start += len(title_lower)
            else:
                start = 0

        end_markers = [
            "apply now interested in this role?",
            "responsible business from pro bono work",
            "our people our people what we do",
        ]
        end = len(text)
        lowered_after_start = lowered[start:]
        for marker in end_markers:
            marker_index = lowered_after_start.find(marker)
            if marker_index > -1:
                end = min(end, start + marker_index)

        description = text[start:end].strip(" -")
        return description or None

    @staticmethod
    def _prepare_response(response: requests.Response) -> None:
        response.raise_for_status()
        response.encoding = "utf-8"
