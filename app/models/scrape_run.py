
from sqlalchemy import Column, Integer, String, DateTime, JSON
from app.database import Base


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"
    id = Column(Integer, primary_key=True)
    firm = Column(String)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    status = Column(String)  # success | failed | partial
    jobs_found = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    logs = Column(JSON, default=list)
