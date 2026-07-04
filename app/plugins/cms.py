from typing import Any

from app.plugins.workday import WorkdayPlugin


class CMSPlugin(WorkdayPlugin):
    plugin_name = "cms"
    display_name = "CMS"
    discoverable = True
    enabled = True
    careers_url = "https://cmno.wd3.myworkdayjobs.com/en-GB/CMS_Career_Site"
    description = "CMS Workday careers scraper"
    required_config = ["api_url", "careers_url"]
    default_config: dict[str, Any] = {
        "api_url": "https://cmno.wd3.myworkdayjobs.com/wday/cxs/cmno/CMS_Career_Site/jobs",
        "careers_url": careers_url,
        "max_pages": 0,
        "fetch_detail_pages": False,
        "request_timeout": 60,
        "detail_timeout": 20,
    }
