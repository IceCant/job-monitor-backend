from typing import Any

from app.plugins.allhires import AllHiresPlugin


class AkinGumpPlugin(AllHiresPlugin):
    plugin_name = "akingump"
    display_name = "Akin Gump"
    discoverable = True
    enabled = True
    careers_url = "https://akingump.allhires.com/app"
    description = "Akin Gump AllHires careers scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "fetch_detail_pages": False,
        "timeout_ms": 60_000,
    }
