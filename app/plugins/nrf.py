from typing import Any

from app.plugins.workday import WorkdayPlugin


class NortonRoseFulbrightPlugin(WorkdayPlugin):
    plugin_name = "nrf"
    display_name = "Norton Rose Fulbright"
    discoverable = True
    enabled = True
    careers_url = "https://nrf.wd3.myworkdayjobs.com/External"
    description = "Norton Rose Fulbright Workday careers scraper"
    required_config = ["api_url", "careers_url"]
    default_config: dict[str, Any] = {
        "api_url": "https://nrf.wd3.myworkdayjobs.com/wday/cxs/nrf/External/jobs",
        "careers_url": careers_url,
        "max_pages": 0,
        "fetch_detail_pages": False,
        "request_timeout": 60,
        "detail_timeout": 20,
    }
