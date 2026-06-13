from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database import get_db
from app.models.scrape_run import ScrapeRun
from app.models.user import User
from app.plugins.registry import get_firm_definition, list_plugins
from app.schemas.api import (
    PluginOut,
    RunRequest,
    ScheduleSettingsOut,
    ScheduleSettingsUpdate,
    ScrapeRunList,
    ScrapeRunOut,
)
from app.services.scheduler_service import scheduler_service
from app.services.scraper_service import run_scrape

router = APIRouter()


@router.get("/plugins", response_model=list[PluginOut])
def get_plugins(current_user: User = Depends(get_current_user)):
    return [PluginOut(**p) for p in list_plugins()]


@router.post("/run", response_model=ScrapeRunOut)
def run(body: RunRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if body.firm_key is None:
        return run_scrape(db, firm_key=None, include_disabled=False)

    try:
        get_firm_definition(body.firm_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return run_scrape(db, firm_key=body.firm_key, include_disabled=True)


@router.get("/runs", response_model=ScrapeRunList)
def list_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ScrapeRun).order_by(ScrapeRun.started_at.desc())
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return ScrapeRunList(
        items=[ScrapeRunOut.model_validate(r) for r in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/schedule", response_model=ScheduleSettingsOut)
def get_schedule(current_user: User = Depends(get_current_user)):
    setting = scheduler_service.refresh_from_db()
    return ScheduleSettingsOut(**setting)


@router.put("/schedule", response_model=ScheduleSettingsOut)
def update_schedule(
    body: ScheduleSettingsUpdate,
    current_user: User = Depends(get_current_user),
):
    setting = scheduler_service.update_schedule(
        enabled=body.enabled,
        interval_hours=max(1, body.interval_hours),
    )
    return ScheduleSettingsOut(**setting)
