from typing import Any

from app.plugins.base import BasePlugin


class JsonExamplePlugin(BasePlugin):
    """Example plugin that returns JSON-like dicts directly."""

    plugin_name = "json_example"
    display_name = "JSON Example Firm"
    enabled = True
    careers_url = "https://example.com/jobs"
    description = "Example plugin returning static JSON job dicts"
    required_config = []
    default_config: dict[str, Any] = {}

    async def scrape(self) -> list[dict[str, Any]]:
        jobs = self.plugin_config.get("jobs")
        if isinstance(jobs, list) and jobs:
            return [dict(job) for job in jobs if isinstance(job, dict)]

        # Fallback demo payload so the plugin works out of the box.
        return [
            {
                "job_url": "https://example.com/jobs/backend-engineer",
                "firm_name": self.firm_name,
                "title": "Backend Engineer",
                "office_location": "Remote",
                "practice_area": "Engineering",
                "pqe_level": "3-5",
                "description": "Design and build backend systems.",
                "source_reference": "JSON-001",
                "status": "LIVE",
                "extra_info": {
                    "source": "json_example",
                },
            },
            {
                "job_url": "https://example.com/jobs/data-engineer",
                "firm_name": self.firm_name,
                "title": "Data Engineer",
                "office_location": "Sydney",
                "practice_area": "Data",
                "pqe_level": "2-4",
                "description": "Build analytics pipelines and ETL jobs.",
                "source_reference": "JSON-002",
                "status": "LIVE",
                "extra_info": {
                    "source": "json_example",
                },
            },
        ]

