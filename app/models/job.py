
from sqlalchemy import Column, Integer, String, JSON, DateTime, ForeignKey
from app.database import Base


class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    firm_id = Column(Integer, ForeignKey("firms.id"))
    firm = Column(String)
    title = Column(String)
    location = Column(String)
    practice_area = Column(String)
    pqe_level = Column(String)
    status = Column(String)
    job_url = Column(String, unique=True)
    first_seen = Column(DateTime)
    last_checked = Column(DateTime)
    extra_info = Column(JSON)
