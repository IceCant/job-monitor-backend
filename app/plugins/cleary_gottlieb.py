from __future__ import annotations

from app.plugins.virecruit import ViRecruitPlugin


class ClearyGottliebPlugin(ViRecruitPlugin):
    plugin_name = "cleary_gottlieb"
    display_name = "Cleary Gottlieb"
    discoverable = True
    enabled = True
    careers_url = (
        "https://legalrecruit-eu.cgsh.com/EUselfapply/viRecruitSelfApply/"
        "RecDefault.aspx?FilterREID=2&FilterJobCategoryID=1"
    )
    description = "Cleary Gottlieb EU viRecruit self-apply scraper"
    source_name = "cleary_gottlieb_virecruit_html"
    default_config = {
        "source_url": careers_url,
        "timeout": 60,
    }

    def extract_pqe(self, title: str, description: str | None) -> str | None:
        lower = title.lower()
        marker = "pqe"
        if marker not in lower:
            return None
        start = max(0, lower.rfind("(", 0, lower.find(marker)))
        end = lower.find(")", lower.find(marker))
        if start >= 0 and end > start:
            return title[start + 1 : end].strip()
        return None
