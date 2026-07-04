from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database import get_db
from app.models.job import Job
from app.models.scrape_run import ScrapeRun
from app.plugins.registry import list_firm_definitions
from app.models.user import User
from app.schemas.api import DashboardStats
from app.services.reporting_service import latest_runs_by_firm

router = APIRouter()


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("", response_model=DashboardStats)
def dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = _today_start()
    firms = list_firm_definitions(include_disabled=True)

    total_firms = len(firms)
    job_totals = db.query(
        func.count(Job.id).filter(Job.status != "REMOVED"),
        func.count(Job.id).filter(Job.status == "NEW", Job.first_seen >= today),
        func.count(Job.id).filter(
            Job.status.in_(["UPDATED", "REPOSTED", "NEEDS_REVIEW"]),
            Job.last_checked >= today,
        ),
        func.count(Job.id).filter(Job.status == "REMOVED", Job.removed_at >= today),
    ).one()
    total_live_jobs, new_jobs_today, updated_jobs_today, removed_jobs_today = job_totals

    latest_runs = latest_runs_by_firm(db, [firm.key for firm in firms])
    failed_sites = sum(
        1 for run in latest_runs.values() if run.status == "failed"
    )

    jobs_by_firm_rows = (
        db.query(Job.firm, func.count(Job.id))
        .filter(Job.status != "REMOVED")
        .group_by(Job.firm)
        .order_by(func.count(Job.id).desc())
        .limit(10)
        .all()
    )
    jobs_by_firm = [{"name": firm or "Unknown", "jobs": count} for firm, count in jobs_by_firm_rows]

    status_rows = db.query(Job.status, func.count(Job.id)).group_by(Job.status).all()
    status_distribution = [
        {"name": (status or "UNKNOWN").title(), "value": count}
        for status, count in status_rows
    ]

    recent_runs = (
        db.query(ScrapeRun)
        .order_by(ScrapeRun.started_at.desc())
        .limit(8)
        .all()
    )
    recent_activity = [
        {
            "type": run.status,
            "firm": run.firm,
            "title": f"Scrape {run.status}",
            "time": run.finished_at,
            "jobs_found": run.jobs_found,
            "errors": run.errors,
        }
        for run in recent_runs
    ]

    return DashboardStats(
        total_firms=total_firms,
        total_live_jobs=total_live_jobs,
        new_jobs_today=new_jobs_today,
        updated_jobs_today=updated_jobs_today,
        removed_jobs_today=removed_jobs_today,
        failed_sites=failed_sites,
        jobs_by_firm=jobs_by_firm,
        status_distribution=status_distribution,
        recent_activity=recent_activity,
    )
