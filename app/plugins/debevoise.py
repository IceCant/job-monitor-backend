from typing import Any

from app.plugins.allhires import AllHiresPlugin


class DebevoisePlugin(AllHiresPlugin):
    plugin_name = "debevoise"
    display_name = "Debevoise & Plimpton"
    discoverable = True
    enabled = True
    careers_url = "https://debevoise.allhires.com/app"
    description = "Debevoise & Plimpton AllHires careers scraper"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "fetch_detail_pages": False,
        "timeout_ms": 60_000,
    }
