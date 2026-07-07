import asyncio
import threading
import unittest
from dataclasses import dataclass
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.job import Job
from app.models.scrape_run import ScrapeRun
from app.schemas.job_result import JobResult
from app.services.scraper_service import (
    _scrape_firms_parallel,
    run_scrape,
)


@dataclass
class FakeFirm:
    key: str
    name: str
    enabled: bool = True


class ParallelScrapingTests(unittest.TestCase):
    def test_runs_firms_up_to_worker_limit(self) -> None:
        lock = threading.Lock()
        two_started = threading.Event()
        active = 0
        max_active = 0

        async def fake_run_firm(firm, progress_callback=None):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
                if active == 2:
                    two_started.set()

            self.assertTrue(two_started.wait(timeout=1))
            await asyncio.sleep(0.02)

            with lock:
                active -= 1
            return []

        firms = [FakeFirm(str(index), f"Firm {index}") for index in range(3)]
        with patch(
            "app.services.scraper_service.run_firm",
            side_effect=fake_run_firm,
        ):
            outcomes = list(_scrape_firms_parallel(firms, max_workers=2))

        self.assertEqual(3, len(outcomes))
        self.assertEqual(2, max_active)
        self.assertTrue(all(outcome.error is None for outcome in outcomes))

    def test_one_failure_does_not_cancel_other_firms(self) -> None:
        async def fake_run_firm(firm, progress_callback=None):
            if firm.key == "bad":
                raise RuntimeError("source unavailable")
            return []

        firms = [FakeFirm("good", "Good"), FakeFirm("bad", "Bad")]
        with patch(
            "app.services.scraper_service.run_firm",
            side_effect=fake_run_firm,
        ):
            outcomes = list(_scrape_firms_parallel(firms, max_workers=2))

        by_key = {outcome.firm.key: outcome for outcome in outcomes}
        self.assertIsNone(by_key["good"].error)
        self.assertRegex(str(by_key["bad"].error), "source unavailable")

    def test_parallel_run_persists_each_firm_and_aggregate_progress(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        firms = [FakeFirm(str(index), f"Firm {index}") for index in range(3)]
        progress_updates = []

        async def fake_run_firm(firm, progress_callback=None):
            if progress_callback is not None:
                progress_callback({"logs": [f"diagnostic:{firm.key}"]})
            await asyncio.sleep(0.01)
            return [
                JobResult(
                    job_url=f"https://example.com/jobs/{firm.key}",
                    firm_name=firm.name,
                    title=f"Job {firm.key}",
                    office_location="London",
                    source_reference=f"ref-{firm.key}",
                )
            ]

        try:
            with (
                patch(
                    "app.services.scraper_service.list_firm_definitions",
                    return_value=firms,
                ),
                patch(
                    "app.services.scraper_service.run_firm",
                    side_effect=fake_run_firm,
                ),
                patch.dict("os.environ", {"SCRAPE_MAX_WORKERS": "2"}),
            ):
                aggregate = run_scrape(
                    session,
                    progress_callback=progress_updates.append,
                )

            self.assertEqual("success", aggregate.status)
            self.assertEqual(3, aggregate.jobs_found)
            self.assertEqual(3, session.query(Job).count())
            self.assertEqual(4, session.query(ScrapeRun).count())
            individual_runs = (
                session.query(ScrapeRun)
                .filter(ScrapeRun.firm_key.is_not(None))
                .all()
            )
            self.assertTrue(
                all(
                    f"diagnostic:{run.firm_key}" in (run.logs or [])
                    for run in individual_runs
                )
            )
            self.assertIn("2 running in parallel", progress_updates[0]["message"])
            self.assertEqual("success", progress_updates[-1]["status"])
            self.assertEqual(3, progress_updates[-1]["completed_firms"])
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
