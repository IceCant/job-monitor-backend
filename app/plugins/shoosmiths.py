from typing import Any

from app.plugins.allhires import AllHiresPlugin


class ShoosmithsPlugin(AllHiresPlugin):
    plugin_name = "shoosmiths"
    display_name = "Shoosmiths"
    discoverable = True
    enabled = True
    careers_url = "https://shoosmiths.allhires.com/app"
    description = "Shoosmiths AllHires careers scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "fetch_detail_pages": False,
        "timeout_ms": 60_000,
    }
