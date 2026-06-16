from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database import SessionLocal, get_db
from app.models.job import Job
from app.models.scrape_run import ScrapeRun
from app.plugins.registry import get_firm_definition, list_firm_definitions
from app.models.user import User
from app.schemas.api import FirmOut, ScrapeStartOut
from app.services.scraper_service import run_scrape

router = APIRouter()


def _run_scrape_background(firm_key: str) -> None:
    db = SessionLocal()
    try:
        run_scrape(db, firm_key=firm_key, include_disabled=True)
    finally:
        db.close()


def _latest_run(db: Session, firm_key: str) -> ScrapeRun | None:
    return (
        db.query(ScrapeRun)
        .filter(ScrapeRun.firm_key == firm_key)
        .order_by(ScrapeRun.started_at.desc())
        .first()
    )


def _to_out(db: Session, firm) -> FirmOut:
    counts = dict(
        db.query(Job.status, func.count(Job.id))
        .filter(Job.firm_key == firm.key)
        .group_by(Job.status)
        .all()
    )
    latest_run = _latest_run(db, firm.key)
    return FirmOut(
        key=firm.key,
        name=firm.name,
        careers_url=firm.careers_url,
        plugin=firm.key,
        plugin_config=firm.default_config,
        active=firm.enabled,
        last_run_at=latest_run.finished_at if latest_run else None,
        last_run_status=latest_run.status if latest_run else None,
        last_error=latest_run.error_message if latest_run else None,
        total_jobs=sum(count for status, count in counts.items() if status != "REMOVED"),
        removed_jobs=counts.get("REMOVED", 0),
        needs_review_jobs=counts.get("NEEDS_REVIEW", 0),
    )


@router.get("", response_model=list[FirmOut])
def list_firms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return [_to_out(db, firm) for firm in list_firm_definitions(include_disabled=True)]


@router.get("/{firm_key}", response_model=FirmOut)
def get_firm(
    firm_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        firm = get_firm_definition(firm_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if firm is None:
        raise HTTPException(status_code=404, detail="Firm not found")
    return _to_out(db, firm)


@router.post("/{firm_key}/run", response_model=ScrapeStartOut, status_code=status.HTTP_202_ACCEPTED)
def run_firm_now(
    firm_key: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    try:
        firm = get_firm_definition(firm_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    background_tasks.add_task(_run_scrape_background, firm_key)
    return ScrapeStartOut(
        message=f"Scrape started for {firm.name}.",
        firm_key=firm_key,
    )
