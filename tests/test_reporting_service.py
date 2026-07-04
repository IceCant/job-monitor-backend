import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.job import Job
from app.models.scrape_run import ScrapeRun
from app.services.reporting_service import (
    job_status_counts_by_firm,
    latest_runs_by_firm,
)


class ReportingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_status_counts_are_grouped_in_one_query(self) -> None:
        self.session.add_all(
            [
                Job(firm_key="alpha", status="LIVE"),
                Job(firm_key="alpha", status="LIVE"),
                Job(firm_key="alpha", status="REMOVED"),
                Job(firm_key="beta", status="NEW"),
            ]
        )
        self.session.commit()

        statements = []
        listener = lambda *args, **kwargs: statements.append(1)
        event.listen(self.engine, "before_cursor_execute", listener)
        try:
            counts = job_status_counts_by_firm(
                self.session, ["alpha", "beta"]
            )
        finally:
            event.remove(self.engine, "before_cursor_execute", listener)

        self.assertEqual(1, len(statements))
        self.assertEqual({"LIVE": 2, "REMOVED": 1}, counts["alpha"])
        self.assertEqual({"NEW": 1}, counts["beta"])

    def test_latest_runs_selects_one_run_per_firm_in_one_query(self) -> None:
        started = datetime(2026, 1, 1)
        self.session.add_all(
            [
                ScrapeRun(
                    firm_key="alpha",
                    firm="Alpha",
                    started_at=started,
                    status="failed",
                ),
                ScrapeRun(
                    firm_key="alpha",
                    firm="Alpha",
                    started_at=started + timedelta(hours=1),
                    status="success",
                ),
                ScrapeRun(
                    firm_key="beta",
                    firm="Beta",
                    started_at=started,
                    status="partial",
                ),
            ]
        )
        self.session.commit()

        statements = []
        listener = lambda *args, **kwargs: statements.append(1)
        event.listen(self.engine, "before_cursor_execute", listener)
        try:
            latest = latest_runs_by_firm(self.session, ["alpha", "beta"])
        finally:
            event.remove(self.engine, "before_cursor_execute", listener)

        self.assertEqual(1, len(statements))
        self.assertEqual("success", latest["alpha"].status)
        self.assertEqual("partial", latest["beta"].status)


if __name__ == "__main__":
    unittest.main()
