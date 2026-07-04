"""Create the current schema and add production query indexes."""

from alembic import op
import sqlalchemy as sa

from app.database import Base
from app.models import app_setting, firm, job, job_change, scrape_run, user  # noqa: F401

revision = "20260702_01"
down_revision = None
branch_labels = None
depends_on = None


JOB_INDEXES = (
    ("ix_jobs_firm_key", ("firm_key",)),
    ("ix_jobs_source_reference", ("source_reference",)),
    ("ix_jobs_firm_key_status", ("firm_key", "status")),
    ("ix_jobs_firm_key_last_seen", ("firm_key", "last_seen")),
    ("ix_jobs_last_seen_checked_id", ("last_seen", "last_checked", "id")),
    ("ix_jobs_status_first_seen", ("status", "first_seen")),
    ("ix_jobs_status_removed_at", ("status", "removed_at")),
    ("ix_jobs_last_checked", ("last_checked",)),
)

SCRAPE_RUN_INDEXES = (
    ("ix_scrape_runs_firm_started", ("firm_key", "started_at")),
    ("ix_scrape_runs_started_at", ("started_at",)),
)

TRIGRAM_INDEXES = (
    ("ix_jobs_title_trgm", "title"),
    ("ix_jobs_firm_trgm", "firm"),
    ("ix_jobs_location_trgm", "location"),
    ("ix_jobs_description_trgm", "full_description"),
)


def _ensure_indexes(table_name: str, indexes) -> None:
    bind = op.get_bind()
    existing = {item["name"] for item in sa.inspect(bind).get_indexes(table_name)}
    for name, columns in indexes:
        if name not in existing:
            op.create_index(name, table_name, list(columns), unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    inspector = sa.inspect(bind)
    if "jobs" in inspector.get_table_names():
        _ensure_indexes("jobs", JOB_INDEXES)
        unique_names = {item["name"] for item in inspector.get_unique_constraints("jobs")}
        if "uq_jobs_firm_match" not in unique_names:
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("jobs") as batch_op:
                    batch_op.create_unique_constraint(
                        "uq_jobs_firm_match", ["firm_key", "match_key"]
                    )
            else:
                op.create_unique_constraint(
                    "uq_jobs_firm_match", "jobs", ["firm_key", "match_key"]
                )

    if "scrape_runs" in inspector.get_table_names():
        _ensure_indexes("scrape_runs", SCRAPE_RUN_INDEXES)

    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        existing = {item["name"] for item in sa.inspect(bind).get_indexes("jobs")}
        for name, column in TRIGRAM_INDEXES:
            if name not in existing:
                op.execute(
                    f"CREATE INDEX {name} ON jobs USING gin ({column} gin_trgm_ops)"
                )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for name, _ in reversed(TRIGRAM_INDEXES):
            op.execute(f"DROP INDEX IF EXISTS {name}")
    for name, _ in reversed(SCRAPE_RUN_INDEXES):
        op.drop_index(name, table_name="scrape_runs", if_exists=True)
    for name, _ in reversed(JOB_INDEXES):
        op.drop_index(name, table_name="jobs", if_exists=True)
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("jobs") as batch_op:
            batch_op.drop_constraint("uq_jobs_firm_match", type_="unique")
    else:
        op.drop_constraint("uq_jobs_firm_match", "jobs", type_="unique")
