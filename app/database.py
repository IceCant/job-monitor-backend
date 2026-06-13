import os
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.schema import CreateColumn

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/jobmonitor",
)

engine_kwargs: dict[str, Any] = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    # check_same_thread=False lets SQLite connection be shared in sync endpoints.
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def _sync_missing_columns(bind, model):
    inspector = inspect(bind)
    table_name = model.__tablename__
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    dialect = bind.dialect

    with bind.begin() as connection:
        for column in model.__table__.columns:
            if column.name in existing_columns:
                continue
            column_sql = str(CreateColumn(column).compile(dialect=dialect))
            connection.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {column_sql}'))


def get_db():
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _backfill_existing_jobs(db):
    from app.models.job import Job
    from app.models.job_change import JobChange
    from datetime import datetime

    for job in db.query(Job).all():
        if not job.firm_key:
            job.firm_key = job.firm
        if not job.match_key:
            if job.job_url:
                job.match_key = f"url:{job.job_url}"
            elif job.title:
                job.match_key = f"legacy:{job.title}"
        if job.last_seen is None:
            job.last_seen = job.last_checked or job.first_seen
        if job.change_history is None:
            job.change_history = []

        has_rows = db.query(JobChange.id).filter(JobChange.job_id == job.id).first() is not None
        if has_rows:
            continue

        for entry in job.change_history:
            ts = entry.get("timestamp")
            if not ts:
                continue
            db.add(
                JobChange(
                    job_id=job.id,
                    firm_key=job.firm_key or job.firm or "unknown",
                    changed_at=datetime.fromisoformat(ts),
                    event=entry.get("event") or "LIVE",
                    message=entry.get("message"),
                    changed_fields=entry.get("changed_fields") or {},
                    snapshot=entry.get("snapshot") or {},
                )
            )


def init_db():
    """Create tables, sync missing columns, and seed baseline application data."""
    # Import models so they register on Base.metadata before create_all.
    from app.core.security import hash_password
    from app.models.app_setting import AppSetting
    from app.models.job_change import JobChange  # noqa: F401
    from app.models.job import Job  # noqa: F401
    from app.models.scrape_run import ScrapeRun  # noqa: F401
    from app.models.user import User

    Base.metadata.create_all(bind=engine)
    for model in (AppSetting, Job, JobChange, ScrapeRun, User):
        _sync_missing_columns(engine, model)

    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            db.add(
                User(
                    username="admin",
                    password_hash=hash_password("admin123"),
                    role="admin",
                )
            )


        setting = db.query(AppSetting).filter(AppSetting.key == "scrape_schedule").first()
        if setting is None:
            db.add(
                AppSetting(
                    key="scrape_schedule",
                    value={"enabled": True, "interval_hours": 24},
                )
            )

        _backfill_existing_jobs(db)
        db.commit()
    finally:
        db.close()
