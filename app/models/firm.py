
from sqlalchemy import Column, Integer, String, Boolean, JSON, DateTime
from app.database import Base


class Firm(Base):
    __tablename__ = "firms"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    careers_url = Column(String)
    plugin = Column(String)
    plugin_config = Column(JSON, default=dict)
    active = Column(Boolean, default=True)
    last_run_at = Column(DateTime)
    last_run_status = Column(String)
