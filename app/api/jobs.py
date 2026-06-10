import io

import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database import get_db
from app.models.job import Job
from app.models.user import User
from app.schemas.api import JobList, JobOut

router = APIRouter()


def _filtered_query(db: Session, search: str | None, status: str | None, firm: str | None):
    query = db.query(Job)
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                Job.title.ilike(like),
                Job.firm.ilike(like),
                Job.practice_area.ilike(like),
                Job.location.ilike(like),
            )
        )
    if status and status.lower() != "all":
        query = query.filter(Job.status == status.upper())
    if firm and firm.lower() != "all":
        query = query.filter(Job.firm == firm)
    return query


@router.get("", response_model=JobList)
def list_jobs(
    search: str | None = None,
    status: str | None = None,
    firm: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = _filtered_query(db, search, status, firm).order_by(Job.last_checked.desc())
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return JobList(
        items=[JobOut.model_validate(j) for j in items],
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = _filtered_query(db, search, status, firm).order_by(Job.firm, Job.title).all()
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
                "Last Checked": j.last_checked,
                "URL": j.job_url,
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
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Jobs")
        data = buffer.getvalue()
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "jobs.xlsx"

    return StreamingResponse(
        io.BytesIO(data),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
