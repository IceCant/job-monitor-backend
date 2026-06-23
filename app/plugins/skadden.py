from typing import Any

from app.plugins.allhires import AllHiresPlugin


class SkaddenPlugin(AllHiresPlugin):
    plugin_name = "skadden"
    display_name = "Skadden"
    discoverable = True
    enabled = True
    careers_url = "https://skadden.allhires.com/app?"
    description = "Skadden AllHires careers scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "fetch_detail_pages": False,
        "timeout_ms": 60_000,
    }
