from typing import Any

from app.plugins.workday import WorkdayPlugin


class FreshfieldsPlugin(WorkdayPlugin):
    plugin_name = "freshfields"
    display_name = "Freshfields"
    discoverable = True
    enabled = True
    careers_url = "https://freshfields.wd3.myworkdayjobs.com/en-US/FBD_101"
    description = "Freshfields Workday careers scraper"
    required_config = ["api_url", "careers_url"]
    default_config: dict[str, Any] = {
        "api_url": "https://freshfields.wd3.myworkdayjobs.com/wday/cxs/freshfields/FBD_101/jobs",
        "careers_url": careers_url,
        "max_pages": 0,
        "fetch_detail_pages": False,
        "request_timeout": 60,
        "detail_timeout": 20,
    }
