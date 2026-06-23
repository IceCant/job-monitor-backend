from app.plugins.workday import WorkdayPlugin


class HoganLovellsPlugin(WorkdayPlugin):
    plugin_name = "hogan_lovells"
    display_name = "Hogan Lovells"
    discoverable = True
    enabled = True
    careers_url = "https://hoganlovells.wd3.myworkdayjobs.com/en-US/Search"
    description = "Hogan Lovells Workday careers scraper"
    required_config = ["api_url", "careers_url"]
    default_config = {
        "api_url": "https://hoganlovells.wd3.myworkdayjobs.com/wday/cxs/hoganlovells/Search/jobs",
        "max_pages": 0,
    }
