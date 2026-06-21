from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.plugins.base import BasePlugin


class ForstersPlugin(BasePlugin):
    plugin_name = "forsters"
    display_name = "Forsters"
    enabled = True
    careers_url = "https://www.forsters.co.uk/vacancies"
    description = "Forsters vacancies scraper"
    required_config = ["source_url"]
    default_config = {
        "source_url": careers_url,
        "fetch_detail_pages": False,
        "timeout": 30,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        source_url = self.plugin_config.get("source_url") or self.careers_url
        timeout = int(self.plugin_config.get("timeout", 30))
        fetch_detail_pages = bool(self.plugin_config.get("fetch_detail_pages", False))

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

        for article in soup.select("main article.vacancy"):
            title = self._text(article, "h5")
            link = article.select_one("a.overlay-link[href]")
            job_url = link.get("href") if link else None
            if not title or not job_url:
                continue

            reference = self._reference(article, job_url)
            if reference in seen:
                continue
            seen.add(reference)

            detail = self._fetch_detail(session, job_url, timeout) if fetch_detail_pages else {}
            jobs.append(
                {
                    "job_url": job_url,
                    "firm_name": self.firm_name,
                    "title": detail.get("title") or title,
                    "office_location": None,
                    "practice_area": self._text(article, ".row span"),
                    "pqe_level": None,
                    "description": detail.get("description") or self._listing_description(article),
                    "source_reference": reference,
                    "status": "LIVE",
                    "extra_info": {
                        "source": "forsters_html",
                        "post_id": self._post_id(article),
                        "vacancy_type": self._class_value(article, "vacancy-type-"),
                        "vacancy_category": self._class_value(article, "vacancy-category-"),
                        "description_source": detail.get("description_source") or "listing_card",
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
        content = soup.select_one("article.vacancy .entry-content")
        title = self._text(content or soup, "h1")
        description = self._html_to_text(content) if content else None
        return {
            "title": title,
            "description": description,
            "description_source": "detail_page" if description else None,
        }

    @staticmethod
    def _listing_description(article) -> str | None:
        overview = article.select_one(".news-overview") or article
        clone = BeautifulSoup(str(overview), "html.parser")
        for element in clone.select(".row, h5, a"):
            element.decompose()
        return ForstersPlugin._clean_text(clone.get_text(" ", strip=True))

    @staticmethod
    def _reference(article, job_url: str) -> str:
        return ForstersPlugin._post_id(article) or urlparse(job_url).path.strip("/") or job_url

    @staticmethod
    def _post_id(article) -> str | None:
        for cls in article.get("class", []):
            if cls.startswith("post-"):
                return cls.removeprefix("post-")
        return None

    @staticmethod
    def _class_value(article, prefix: str) -> str | None:
        for cls in article.get("class", []):
            if cls.startswith(prefix):
                return cls.removeprefix(prefix)
        return None

    @staticmethod
    def _html_to_text(element) -> str | None:
        clone = BeautifulSoup(str(element), "html.parser")
        for item in clone.select("script, style, a.btn"):
            item.decompose()
        return ForstersPlugin._clean_text(clone.get_text("\n", strip=True))

    @staticmethod
    def _text(root, selector: str) -> str | None:
        if root is None:
            return None
        element = root.select_one(selector)
        if element is None:
            return None
        return ForstersPlugin._clean_text(element.get_text(" ", strip=True))

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
