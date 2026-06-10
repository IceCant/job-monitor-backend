"""Pydantic schemas for API request/response bodies."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


# --- auth -------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# --- jobs -------------------------------------------------------------------

class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    firm: str | None = None
    title: str | None = None
    location: str | None = None
    practice_area: str | None = None
    pqe_level: str | None = None
    status: str | None = None
    job_url: str | None = None
    first_seen: datetime | None = None
    last_checked: datetime | None = None
    extra_info: dict[str, Any] | None = None


class JobList(BaseModel):
    items: list[JobOut]
    total: int
    page: int
    page_size: int


# --- firms ------------------------------------------------------------------

class FirmOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str | None = None
    careers_url: str | None = None
    plugin: str | None = None
    plugin_config: dict[str, Any] | None = None
    active: bool | None = None
    last_run_at: datetime | None = None
    last_run_status: str | None = None
    total_jobs: int = 0


class FirmCreate(BaseModel):
    name: str
    careers_url: str | None = None
    plugin: str = "workday"
    plugin_config: dict[str, Any] = {}
    active: bool = True


class FirmUpdate(BaseModel):
    name: str | None = None
    careers_url: str | None = None
    plugin: str | None = None
    plugin_config: dict[str, Any] | None = None
    active: bool | None = None


# --- scrape runs ------------------------------------------------------------

class ScrapeRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    firm: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str | None = None
    jobs_found: int = 0
    errors: int = 0
    logs: list[str] | None = None


class ScrapeRunList(BaseModel):
    items: list[ScrapeRunOut]
    total: int
    page: int
    page_size: int


class RunRequest(BaseModel):
    firm_id: int | None = None


# --- schedule ---------------------------------------------------------------

class ScheduleSettingsOut(BaseModel):
    enabled: bool
    interval_hours: int


class ScheduleSettingsUpdate(BaseModel):
    enabled: bool = True
    interval_hours: int = 6


# --- dashboard --------------------------------------------------------------

class DashboardStats(BaseModel):
    total_firms: int
    total_live_jobs: int
    new_jobs_today: int
    updated_jobs_today: int
    removed_jobs_today: int
    failed_sites: int
    jobs_by_firm: list[dict[str, Any]]
    status_distribution: list[dict[str, Any]]
    recent_activity: list[dict[str, Any]]
