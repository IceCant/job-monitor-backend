import io
from datetime import datetime
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database import get_db
from app.models.job_change import JobChange
from app.models.job import Job
from app.models.user import User
from app.schemas.api import JobHistoryEntry, JobList, JobOut

router = APIRouter()


def _history_out(db: Session, job_id: int) -> list[JobHistoryEntry]:
    rows = (
        db.query(JobChange)
        .filter(JobChange.job_id == job_id)
        .order_by(JobChange.changed_at.asc(), JobChange.id.asc())
        .all()
    )
    return [
        JobHistoryEntry(
            timestamp=row.changed_at,
            event=row.event,
            message=row.message,
            changed_fields=row.changed_fields or {},
            snapshot=row.snapshot or {},
        )
        for row in rows
    ]


def _job_out(job: Any, *, history: list[JobHistoryEntry] | None = None) -> JobOut:
    out = JobOut.model_validate(job)
    out.change_history = history or []
    return out


def _filtered_query(
    db: Session,
    search: str | None,
    status: str | None,
    firm: str | None,
    changed_only: bool,
    seen_from: datetime | None,
    seen_to: datetime | None,
):
    query = db.query(Job)
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                Job.title.ilike(like),
                Job.firm.ilike(like),
                Job.practice_area.ilike(like),
                Job.location.ilike(like),
                Job.full_description.ilike(like),
                Job.source_reference.ilike(like),
            )
        )
    if status and status.lower() != "all":
        query = query.filter(Job.status == status.upper())
    if firm and firm.lower() != "all":
        query = query.filter(or_(Job.firm == firm, Job.firm_key == firm))
    if changed_only:
        query = query.filter(Job.status.in_(["UPDATED", "REPOSTED", "NEEDS_REVIEW"]))
    if seen_from is not None:
        query = query.filter(Job.last_seen >= seen_from)
    if seen_to is not None:
        query = query.filter(Job.last_seen <= seen_to)
    return query


@router.get("", response_model=JobList)
def list_jobs(
    search: str | None = None,
    status: str | None = None,
    firm: str | None = None,
    changed_only: bool = False,
    seen_from: datetime | None = None,
    seen_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = _filtered_query(db, search, status, firm, changed_only, seen_from, seen_to).order_by(Job.last_seen.desc(), Job.last_checked.desc())
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return JobList(
        items=[_job_out(j) for j in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/export")
def export_jobs(
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    search: str | None = None,
    status: str | None = None,
    firm: str | None = None,
    changed_only: bool = False,
    seen_from: datetime | None = None,
    seen_to: datetime | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = _filtered_query(db, search, status, firm, changed_only, seen_from, seen_to).order_by(Job.firm, Job.title).all()
    df = pd.DataFrame(
        [
            {
                "Firm": j.firm,
                "Title": j.title,
                "Location": j.location,
                "Practice Area": j.practice_area,
                "PQE": j.pqe_level,
                "Status": j.status,
                "First Seen": j.first_seen,
                "Last Seen": j.last_seen,
                "Removed Date": j.removed_at,
                "Last Checked": j.last_checked,
                "Reference": j.source_reference,
                "URL": j.job_url,
                "Description": j.full_description,
            }
            for j in rows
        ]
    )

    if format == "csv":
        buffer = io.StringIO()
        df.to_csv(buffer, index=False)
        data = buffer.getvalue().encode()
        media = "text/csv"
        filename = "jobs.csv"
    else:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:  # type: ignore[arg-type]
            df.to_excel(writer, index=False, sheet_name="Jobs")
        data = buffer.getvalue()
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "jobs.xlsx"

    return StreamingResponse(
        io.BytesIO(data),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_out(job, history=_history_out(db, job_id))

