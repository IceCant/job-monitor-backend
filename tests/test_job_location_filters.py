import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.jobs import _filtered_query, list_job_location_options
from app.database import Base
from app.models.job import Job


class JobLocationFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.session.add_all(
            [
                Job(
                    firm_key="a",
                    firm="Firm A",
                    title="Washington Role",
                    location="Washington DC",
                    status="LIVE",
                    match_key="a",
                    extra_info={},
                ),
                Job(
                    firm_key="b",
                    firm="Firm B",
                    title="Washington United States Role",
                    location="Washington, United States",
                    status="LIVE",
                    match_key="b",
                    extra_info={},
                ),
                Job(
                    firm_key="c",
                    firm="Firm C",
                    title="Northern Offices Role",
                    location=(
                        "Manchester, United Kingdom; Birmingham, United Kingdom; "
                        "London, United Kingdom; Leeds, United Kingdom"
                    ),
                    status="LIVE",
                    match_key="c",
                    extra_info={},
                ),
            ]
        )
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_location_options_are_canonical_and_split(self) -> None:
        options = list_job_location_options(
            db=self.session,
            current_user=object(),
        )["items"]

        self.assertIn("Washington DC", options)
        self.assertIn("Manchester", options)
        self.assertIn("Birmingham", options)
        self.assertIn("London", options)
        self.assertIn("Leeds", options)
        self.assertNotIn("Manchester, United Kingdom", options)

    def test_location_filter_matches_aliases_and_multi_location_rows(self) -> None:
        washington_rows = _filtered_query(
            self.session,
            search=None,
            status=None,
            firm=None,
            location=["Washington DC"],
            changed_only=False,
            seen_from=None,
            seen_to=None,
        ).all()
        self.assertEqual(
            {"Washington Role", "Washington United States Role"},
            {row.title for row in washington_rows},
        )

        manchester_rows = _filtered_query(
            self.session,
            search=None,
            status=None,
            firm=None,
            location=["Manchester"],
            changed_only=False,
            seen_from=None,
            seen_to=None,
        ).all()
        self.assertEqual(["Northern Offices Role"], [row.title for row in manchester_rows])


if __name__ == "__main__":
    unittest.main()
