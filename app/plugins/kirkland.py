from typing import Any

from app.plugins.ashurst_perkins_coie import AshurstPerkinsCoiePlugin


class KirklandPlugin(AshurstPerkinsCoiePlugin):
    plugin_name = "kirkland"
    display_name = "Kirkland & Ellis"
    enabled = True
    careers_url = "https://fsr.cvmailuk.com/kirkland/main.cfm?srxksl=1"
    description = "Kirkland & Ellis CVMail careers scraper"
    source_name = "kirkland_cvmail_html"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "fetch_detail_pages": True,
        "max_pages": 0,
        "timeout": 30,
        "detail_timeout": 8,
    }
