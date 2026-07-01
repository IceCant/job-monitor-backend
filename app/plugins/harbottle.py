from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import requests

from app.plugins.base import BasePlugin


class HarbottlePlugin(BasePlugin):
    plugin_name = "harbottle"
    display_name = "Harbottle & Lewis"
    enabled = True
    careers_url = "https://harbottle.appx.candidats.io/roles"
    description = "Harbottle & Lewis Candid ATS careers scraper"
    required_config = ["source_url"]
    default_config = {
        "source_url": careers_url,
        "api_base_url": "https://apiapp-prodlateral.candidats.io/vantage/api/public",
        "organization_id": "f404b56c-e178-4202-b314-b48929c02b97",
        "subdomain": "harbottle.appx.candidats.io",
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        cfg = {**self.default_config, **(self.plugin_config or {})}
        api_base_url = str(cfg["api_base_url"]).rstrip("/")
        organization_id = str(cfg["organization_id"])
        subdomain = str(cfg["subdomain"])
        public_base_url = self._public_base_url(str(cfg.get("source_url") or self.careers_url))
        timeout = int(cfg.get("timeout", 60))

        session = requests.Session()
        session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
            }
        )

        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 0

        while True:
            payload = self._fetch_roles_page(
                session,
                api_base_url,
                organization_id,
                subdomain,
                page,
                timeout,
            )
            roles = payload.get("content") or []
            if not isinstance(roles, list):
                raise ValueError("Harbottle roles response did not contain a role list")

            for role in roles:
                if not isinstance(role, dict):
                    continue

                title = self._clean(role.get("value"))
                role_id = self._clean(role.get("id"))
                reference = self._clean(role.get("requisition")) or role_id
                if not title or not role_id or not reference or reference in seen:
                    continue

                seen.add(reference)
                jobs.append(
                    {
                        "job_url": f"{public_base_url}/apply/{role_id}",
                        "firm_name": self.firm_name,
                        "title": title,
                        "office_location": self._locations(role),
                        "practice_area": self._nested_value(role, "department"),
                        "pqe_level": self._pqe_level(role),
                        "description": None,
                        "source_reference": reference,
                        "status": "LIVE",
                        "extra_info": {
                            "source": "candidats_api",
                            "role_id": role_id,
                            "requisition": self._clean(role.get("requisition")),
                            "employment_type": self._nested_value(role, "employmentType"),
                            "role_level": self._nested_value(role, "roleLevel"),
                            "start_date_time": role.get("startDateTime"),
                        },
                    }
                )

            if not payload.get("hasNext"):
                break
            page += 1

        if not jobs:
            raise ValueError("Harbottle scrape returned no jobs")

        return jobs

    @staticmethod
    def _fetch_roles_page(
        session: requests.Session,
        api_base_url: str,
        organization_id: str,
        subdomain: str,
        page: int,
        timeout: int,
    ) -> dict[str, Any]:
        query = urlencode(
            {
                "page": page,
                "subdomain": subdomain,
                "languageCode": "en",
            }
        )
        response = session.post(
            f"{api_base_url}/{organization_id}/roles?{query}",
            json={"searchTerm": ""},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Harbottle roles response was not a JSON object")
        return payload

    @classmethod
    def _locations(cls, role: dict[str, Any]) -> str | None:
        locations = role.get("locations") or []
        if not isinstance(locations, list):
            return None
        values = [
            cls._clean(location.get("value"))
            for location in locations
            if isinstance(location, dict)
        ]
        return "; ".join(value for value in values if value) or None

    @classmethod
    def _nested_value(cls, role: dict[str, Any], key: str) -> str | None:
        value = role.get(key)
        if not isinstance(value, dict):
            return None
        return cls._clean(value.get("value"))

    @classmethod
    def _pqe_level(cls, role: dict[str, Any]) -> str | None:
        title = cls._clean(role.get("value")) or ""
        match = re.search(r"\b(?:NQ\s*-\s*)?\d+\s*(?:-\s*\d+)?\s*PQE\b", title, re.IGNORECASE)
        if match:
            return " ".join(match.group(0).split())
        return cls._nested_value(role, "roleLevel")

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", str(value)).strip()
        return text or None

    @staticmethod
    def _public_base_url(source_url: str) -> str:
        parsed = urlparse(source_url)
        return urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")
