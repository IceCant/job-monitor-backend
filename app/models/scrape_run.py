
from sqlalchemy import Column, DateTime, Index, Integer, JSON, String
from app.database import Base


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"
    __table_args__ = (
        Index("ix_scrape_runs_firm_started", "firm_key", "started_at"),
        Index("ix_scrape_runs_started_at", "started_at"),
    )
    id = Column(Integer, primary_key=True)
    firm_key = Column(String)
    firm = Column(String)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    status = Column(String)  # success | failed | partial
    jobs_found = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    error_message = Column(String)
    logs = Column(JSON, default=list)
