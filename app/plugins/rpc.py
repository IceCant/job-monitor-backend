from typing import Any

from app.plugins.ashurst_perkins_coie import AshurstPerkinsCoiePlugin


class RPCPlugin(AshurstPerkinsCoiePlugin):
    plugin_name = "rpc"
    display_name = "RPC"
    enabled = True
    careers_url = "https://fsr.cvmailuk.com/rpc/main.cfm?srxksl=1"
    description = "RPC CVMail careers scraper"
    source_name = "rpc_cvmail_html"
    required_config = ["source_url"]
    default_config: dict[str, Any] = {
        "source_url": careers_url,
        "fetch_detail_pages": False,
        "max_pages": 0,
        "timeout": 30,
        "detail_timeout": 8,
    }
