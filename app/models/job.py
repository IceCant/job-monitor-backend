from sqlalchemy import Column, DateTime, Index, Integer, JSON, String, Text, UniqueConstraint
from app.database import Base


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("firm_key", "match_key", name="uq_jobs_firm_match"),
        Index("ix_jobs_firm_key_status", "firm_key", "status"),
        Index("ix_jobs_firm_key_last_seen", "firm_key", "last_seen"),
    )

    id = Column(Integer, primary_key=True)
    firm_id = Column(Integer, nullable=True)
    firm_key = Column(String, nullable=True, index=True)
    firm = Column(String)
    title = Column(String)
    location = Column(String)
    practice_area = Column(String)
    pqe_level = Column(String)
    status = Column(String)
    job_url = Column(String, nullable=True)
    match_key = Column(String, nullable=True)
    source_reference = Column(String, nullable=True, index=True)
    first_seen = Column(DateTime)
    last_seen = Column(DateTime)
    last_checked = Column(DateTime)
    removed_at = Column(DateTime, nullable=True)
    full_description = Column(Text, nullable=True)
    change_history = Column(JSON, default=list)
    extra_info = Column(JSON)
