import os
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_DB = Path("/tmp/job_monitor_plugin_test.db")
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

from app.database import SessionLocal, init_db  # noqa: E402
from app.models.job_change import JobChange  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.plugins.sample.json_example import JsonExamplePlugin  # noqa: E402
from app.services.scraper_service import run_scrape  # noqa: E402


RUN_1 = {
    "jobs": [
        {
            "job_url": "https://example.com/jobs/1",
            "firm_name": "JSON Example Firm",
            "title": "Associate",
            "office_location": "Melbourne",
            "practice_area": "Corporate",
            "pqe_level": "2-4",
            "description": "First description",
            "source_reference": "REF-1",
            "status": "LIVE",
            "extra_info": {"title": "Associate"},
        },
        {
            "job_url": "https://example.com/jobs/2",
            "firm_name": "JSON Example Firm",
            "title": "Analyst",
            "office_location": "Sydney",
            "practice_area": "Finance",
            "pqe_level": "1-3",
            "description": "Second description",
            "source_reference": "REF-2",
            "status": "LIVE",
            "extra_info": {"title": "Analyst"},
        },
    ]
}

RUN_2 = {
    "jobs": [
        {
            "job_url": "https://example.com/jobs/1",
            "firm_name": "JSON Example Firm",
            "title": "Associate",
            "office_location": None,
            "practice_area": "Corporate",
            "pqe_level": "2-4",
            "description": "First description",
            "source_reference": "REF-1",
            "status": "LIVE",
            "extra_info": {"title": "Associate"},
        }
    ]
}

RUN_3 = {
    "jobs": [
        {
            "job_url": "https://example.com/jobs/1",
            "firm_name": "JSON Example Firm",
            "title": "Associate",
            "office_location": "Melbourne",
            "practice_area": "Corporate",
            "pqe_level": "2-4",
            "description": "First description updated",
            "source_reference": "REF-1",
            "status": "LIVE",
            "extra_info": {"title": "Associate"},
        },
        {
            "job_url": "https://example.com/jobs/2",
            "firm_name": "JSON Example Firm",
            "title": "Analyst",
            "office_location": "Sydney",
            "practice_area": "Finance",
            "pqe_level": "1-3",
            "description": "Second description",
            "source_reference": "REF-2",
            "status": "LIVE",
            "extra_info": {"title": "Analyst"},
        },
    ]
}


def run_once(payload: dict):
    JsonExamplePlugin.default_config = payload
    with SessionLocal() as db:
        return run_scrape(db, firm_key="json_example", include_disabled=True)


def run_failure_once():
    original_scrape = JsonExamplePlugin.scrape

    async def failing_scrape(self):
        raise RuntimeError("simulated scrape failure")

    JsonExamplePlugin.scrape = failing_scrape
    try:
        with SessionLocal() as db:
            return run_scrape(db, firm_key="json_example", include_disabled=True)
    finally:
        JsonExamplePlugin.scrape = original_scrape


if __name__ == "__main__":
    init_db()
    run_once(RUN_1)
    run_once(RUN_2)
    run_once(RUN_3)
    failed_run = run_failure_once()
    print({"failed_run_status": failed_run.status, "failed_run_error": failed_run.error_message})

    with SessionLocal() as db:
        jobs = db.execute(select(Job).order_by(Job.job_url)).scalars().all()
        changes = db.execute(select(JobChange).order_by(JobChange.id)).scalars().all()
        assert failed_run.status == "failed", "Failure run should be marked failed"
        assert all(job.status != "REMOVED" for job in jobs), "Failed scrape must not mark jobs removed"
        assert len(changes) >= 5, "Expected multiple job history rows in job_changes"

        print({"job_changes": len(changes)})
        for job in jobs:
            print(
                {
                    "job_url": job.job_url,
                    "status": job.status,
                    "first_seen": bool(job.first_seen),
                    "last_seen": bool(job.last_seen),
                    "removed_at": bool(job.removed_at),
                    "history_events": [entry.get("event") for entry in (job.change_history or [])],
                }
            )



