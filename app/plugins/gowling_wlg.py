from typing import Any

from app.plugins.oracle_hcm import OracleHCMPlugin


class GowlingWLGPlugin(OracleHCMPlugin):
    plugin_name = "gowling_wlg"
    display_name = "Gowling WLG"
    discoverable = True
    enabled = True
    careers_url = "https://ehjc.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_17/jobs"
    description = "Gowling WLG Oracle HCM careers scraper"
    required_config = ["api_url", "careers_url", "site_number"]
    default_config: dict[str, Any] = {
        "api_url": "https://ehjc.fa.em2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
        "careers_url": careers_url,
        "site_number": "CX_17",
        "limit": 25,
        "max_pages": 0,
        "sort_by": "POSTING_DATES_DESC",
        "timeout": 60,
    }
