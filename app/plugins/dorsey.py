from __future__ import annotations

from typing import Any

from app.plugins.virecruit import ViRecruitPlugin


class DorseyPlugin(ViRecruitPlugin):
    plugin_name = "dorsey"
    display_name = "Dorsey"
    discoverable = True
    enabled = True
    careers_url = (
        "https://recruiting.dorsey.com/viRecruitSelfApply/"
        "RecDefault.aspx?FilterREID=2&FilterJobCategoryID=1"
    )
    description = "Dorsey viRecruit self-apply scraper"
    source_name = "dorsey_virecruit_html"
    default_config = {
        "source_url": careers_url,
        "timeout": 60,
    }

    async def scrape(self) -> list[dict[str, Any]]:
        jobs = await super().scrape()
        for job in jobs:
            location = str(job.get("office_location") or "").strip()
            if location.lower() in {"", "zunknown", "unknown"}:
                job["office_location"] = self._extract_location(
                    str(job.get("title") or ""),
                    job.get("description"),
                )
        return jobs

    @staticmethod
    def _extract_location(title: str, description: Any) -> str | None:
        description_text = str(description or "")
        lines = [line.strip() for line in description_text.splitlines() if line.strip()]

        for index, line in enumerate(lines):
            if line != "Office Location:":
                continue

            locations: list[str] = []
            for value in lines[index + 1 :]:
                if value.endswith(":") or value.startswith("#"):
                    break
                locations.append(value)
            if locations:
                return "; ".join(locations)

        if " - " in title:
            location = title.rsplit(" - ", 1)[-1].strip()
            return location or None

        if "any office location" in title.lower():
            return "Any Office Location"

        return None
