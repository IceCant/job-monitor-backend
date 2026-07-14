"""Pydantic schemas for API request/response bodies."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# --- auth -------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class GoogleLoginRequest(BaseModel):
    id_token: str


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

class JobHistoryEntry(BaseModel):
    timestamp: datetime
    event: str
    message: str | None = None
    changed_fields: dict[str, Any] | None = None
    snapshot: dict[str, Any] | None = None

class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    firm_key: str | None = None
    firm: str | None = None
    title: str | None = None
    location: str | None = None
    practice_area: str | None = None
    pqe_level: str | None = None
    status: str | None = None
    job_url: str | None = None
    source_reference: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    last_checked: datetime | None = None
    removed_at: datetime | None = None
    full_description: str | None = None
    change_history: list[JobHistoryEntry] = Field(default_factory=list)
    extra_info: dict[str, Any] | None = None


class JobList(BaseModel):
    items: list[JobOut]
    total: int
    page: int
    page_size: int


# --- firms ------------------------------------------------------------------

class FirmOut(BaseModel):
    key: str
    name: str | None = None
    careers_url: str | None = None
    plugin: str | None = None
    plugin_config: dict[str, Any] | None = None
    active: bool | None = None
    last_run_at: datetime | None = None
    last_run_status: str | None = None
    last_error: str | None = None
    total_jobs: int = 0
    removed_jobs: int = 0
    needs_review_jobs: int = 0


class FirmCreate(BaseModel):
    name: str | None = None


class FirmUpdate(BaseModel):
    active: bool | None = None


# --- scrape runs ------------------------------------------------------------

class ScrapeRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    firm_key: str | None = None
    firm: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str | None = None
    jobs_found: int = 0
    errors: int = 0
    error_message: str | None = None
    logs: list[str] | None = None


class ScrapeRunList(BaseModel):
    items: list[ScrapeRunOut]
    total: int
    page: int
    page_size: int


class ScrapeStartOut(BaseModel):
    accepted: bool = True
    message: str
    run_id: str | None = None
    firm_key: str | None = None


class ScrapeProgressOut(BaseModel):
    run_id: str
    status: str
    label: str
    firm_key: str | None = None
    current_firm: str | None = None
    current_firm_percent: int = 0
    current_firm_stage: str | None = None
    total_firms: int = 0
    completed_firms: int = 0
    percent: int = 0
    jobs_found: int = 0
    errors: int = 0
    message: str | None = None
    logs: list[str] = Field(default_factory=list)
    started_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class RunRequest(BaseModel):
    firm_key: str | None = None


class PluginOut(BaseModel):
    key: str
    name: str
    class_name: str
    enabled: bool = True
    careers_url: str | None = None
    description: str = ""
    required_config: list[str] = Field(default_factory=list)
    default_config: dict[str, Any] = Field(default_factory=dict)


class PluginTestRequest(BaseModel):
    plugin_key: str
    config: dict[str, Any] = Field(default_factory=dict)
    firm_name: str | None = None
    limit: int = Field(default=10, ge=1, le=100)


class PluginTestOut(BaseModel):
    plugin_key: str
    firm_name: str
    count: int
    elapsed_ms: int
    items: list[dict[str, Any]]
    raw_json: str


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
