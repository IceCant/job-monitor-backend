from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class JobResult:
    job_url: str
    firm_name: str

    office_location: str | None = None
    practice_area: str | None = None
    pqe_level: str | None = None

    status: str = "LIVE"

    extra_info: Dict[str, Any] | None = None