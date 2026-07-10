from __future__ import annotations

from typing import Any

from app.plugins.earcu_position_browser import EarcuPositionBrowserPlugin


class IrwinMitchellPlugin(EarcuPositionBrowserPlugin):
    plugin_name = "irwin_mitchell"
    display_name = "Irwin Mitchell"
    discoverable = True
    enabled = True
    careers_url = "https://careers.irwinmitchell.com/jobs/vacancy/find/results/"
    description = "Irwin Mitchell Earcu careers scraper"
    required_config = ["source_url"]
    source_name = "irwin_mitchell_earcu_html"
    column_map = {
        "office_location": "codelist5value",
        "practice_area": "codelist9value",
        "sub_department": "codelist16value",
        "contract_type": "codelist7value",
        "hours_type": "codelist10value",
    }
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "max_pages": 0,
        "safety_max_pages": 100,
        "timeout": 60,
    }
