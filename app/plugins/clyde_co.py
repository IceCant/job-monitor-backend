from typing import Any

from app.plugins.workday import WorkdayPlugin


class ClydeCoPlugin(WorkdayPlugin):
    plugin_name = "clyde_co"
    display_name = "Clyde & Co"
    discoverable = True
    enabled = True
    careers_url = "https://clydeco.wd103.myworkdayjobs.com/en-GB/clydecocareers"
    description = "Clyde & Co Workday careers scraper"
    required_config = ["api_url", "careers_url"]
    default_config: dict[str, Any] = {
        "api_url": "https://clydeco.wd103.myworkdayjobs.com/wday/cxs/clydeco/clydecocareers/jobs",
        "careers_url": careers_url,
        "max_pages": 0,
        "fetch_detail_pages": False,
        "request_timeout": 60,
        "request_retries": 2,
        "detail_timeout": 20,
    }
