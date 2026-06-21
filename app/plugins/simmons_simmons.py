from typing import Any

from app.plugins.workday import WorkdayPlugin


class SimmonsSimmonsPlugin(WorkdayPlugin):
    plugin_name = "simmons_simmons"
    display_name = "Simmons & Simmons"
    enabled = True
    careers_url = "https://wd3.myworkdaysite.com/en-US/recruiting/simmonssimmons/SimmonsSimmonsExternal"
    description = "Simmons & Simmons Workday scraper"
    required_config = ["api_url", "careers_url"]
    default_config: dict[str, Any] = {
        "api_url": "https://wd3.myworkdaysite.com/wday/cxs/simmonssimmons/SimmonsSimmonsExternal/jobs",
        "careers_url": careers_url,
        "max_pages": 0,
        "fetch_detail_pages": False,
        "request_timeout": 60,
        "detail_timeout": 20,
    }
