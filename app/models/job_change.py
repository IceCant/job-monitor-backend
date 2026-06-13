from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String

from app.database import Base


class JobChange(Base):
    __tablename__ = "job_changes"
    __table_args__ = (
        Index("ix_job_changes_job_id_changed_at", "job_id", "changed_at"),
        Index("ix_job_changes_firm_key_changed_at", "firm_key", "changed_at"),
    )

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    firm_key = Column(String, nullable=False)
    changed_at = Column(DateTime, nullable=False)
    event = Column(String, nullable=False)
    message = Column(String, nullable=True)
    changed_fields = Column(JSON, default=dict)
    snapshot = Column(JSON, default=dict)

