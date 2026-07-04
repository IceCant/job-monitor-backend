import os
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

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


def get_db():
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Seed baseline application data after Alembic has prepared the schema."""
    from app.core.security import hash_password
    from app.models.app_setting import AppSetting
    from app.models.user import User

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
        db.commit()
    finally:
        db.close()
