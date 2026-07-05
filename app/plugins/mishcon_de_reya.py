from typing import Any

from app.plugins.ashurst_perkins_coie import AshurstPerkinsCoiePlugin


class MishconDeReyaPlugin(AshurstPerkinsCoiePlugin):
    plugin_name = "mishcon_de_reya"
    display_name = "Mishcon de Reya"
    enabled = True
    careers_url = "https://fsr.cvmailuk.com/mishcon/main.cfm?srxksl=1"
    description = "Mishcon de Reya CVMail careers scraper"
    source_name = "mishcon_de_reya_cvmail_html"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "fetch_detail_pages": False,
        "max_pages": 0,
        "timeout": 30,
        "detail_timeout": 8,
    }
