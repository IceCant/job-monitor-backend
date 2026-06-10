from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///jobmonitor.db"

# check_same_thread=False lets the SQLite connection be shared across the
# threads FastAPI uses to run sync endpoints.
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
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
    """Create tables and seed a default admin user + demo firm on first run."""
    # Import models so they register on Base.metadata before create_all.
    from app.core.security import hash_password
    from app.models.app_setting import AppSetting
    from app.models.firm import Firm
    from app.models.job import Job  # noqa: F401
    from app.models.scrape_run import ScrapeRun  # noqa: F401
    from app.models.user import User

    Base.metadata.create_all(bind=engine)

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

        if db.query(Firm).count() == 0:
            # A real, public Workday board so the scraper works out of the box.
            db.add(
                Firm(
                    name="Workday",
                    careers_url=(
                        "https://nrf.wd3.myworkdayjobs.com/External"
                        "Workday"
                    ),
                    plugin="workday",
                    plugin_config={
                        "api_url": (
                            "https://nrf.wd3.myworkdayjobs.com/wday/cxs/nrf/External/jobs"
                        ),
                        "careers_url": (
                            "https://nrf.wd3.myworkdayjobs.com/External"
                        ),
                        "max_pages": 0,
                    },
                    active=True,
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
