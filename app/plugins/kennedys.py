from __future__ import annotations

from typing import Any

from app.plugins.earcu_position_browser import EarcuPositionBrowserPlugin


class KennedysPlugin(EarcuPositionBrowserPlugin):
    plugin_name = "kennedys"
    display_name = "Kennedys"
    discoverable = True
    enabled = True
    careers_url = "https://careers.kennedyslaw.com/jobs/vacancy/find/results/"
    description = "Kennedys Earcu careers scraper"
    required_config = ["source_url"]
    source_name = "kennedys_earcu_html"
    column_map = {
        "office_location": "codelist5value",
        "work_arrangement": "codelist20value",
    }
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "max_pages": 0,
        "safety_max_pages": 100,
        "timeout": 60,
    }
