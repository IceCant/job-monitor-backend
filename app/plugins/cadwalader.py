from __future__ import annotations

import re

from app.plugins.virecruit import ViRecruitPlugin


class CadwaladerPlugin(ViRecruitPlugin):
    plugin_name = "cadwalader"
    display_name = "Cadwalader"
    discoverable = True
    enabled = True
    careers_url = (
        "https://recruiting.cwt.com/videsktop/viRecruitSelfApply/"
        "RecDefault.aspx?FilterREID=2&FilterJobCategoryID=10"
    )
    description = "Cadwalader viRecruit self-apply scraper"
    source_name = "cadwalader_virecruit_html"
    default_config = {
        "source_url": careers_url,
        "timeout": 60,
    }

    def extract_pqe(self, title: str, description: str | None) -> str | None:
        title_match = re.search(r"\((\d+\s*(?:-\s*\d+\+?|\+)?\s*Years?)\)", title, re.IGNORECASE)
        if title_match:
            return " ".join(title_match.group(1).split())

        text = f"{title} {description or ''}"
        patterns = [
            r"(\d+\s*(?:\+|-\s*\d+)?\s+years?\s+of\s+(?:substantial\s+)?experience)",
            r"(\d+\s*(?:\+|-\s*\d+)?\s+years?\s+PQE)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return " ".join(match.group(1).split())
        return None
