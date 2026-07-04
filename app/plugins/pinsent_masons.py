from typing import Any

from app.plugins.oracle_hcm import OracleHCMPlugin


class PinsentMasonsPlugin(OracleHCMPlugin):
    plugin_name = "pinsent_masons"
    display_name = "Pinsent Masons"
    discoverable = True
    enabled = True
    careers_url = (
        "https://ehpy.fa.em5.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs"
        "?mode=location&sortBy=POSTING_DATES_DESC"
    )
    description = "Pinsent Masons Oracle HCM careers scraper"
    required_config = ["api_url", "careers_url", "site_number"]
    default_config: dict[str, Any] = {
        "api_url": "https://ehpy.fa.em5.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
        "careers_url": careers_url,
        "site_number": "CX_1001",
        "limit": 25,
        "max_pages": 0,
        "sort_by": "POSTING_DATES_DESC",
        "timeout": 60,
    }
