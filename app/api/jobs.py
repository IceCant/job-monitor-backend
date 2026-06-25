import io
import json
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database import get_db
from app.models.job_change import JobChange
from app.models.job import Job
from app.models.user import User
from app.schemas.api import JobHistoryEntry, JobList, JobOut

router = APIRouter()

SORT_COLUMNS = {
    "firm": Job.firm,
    "title": Job.title,
    "location": Job.location,
    "practice_area": Job.practice_area,
    "pqe_level": Job.pqe_level,
    "status": Job.status,
    "first_seen": Job.first_seen,
    "last_seen": Job.last_seen,
    "last_checked": Job.last_checked,
    "removed_at": Job.removed_at,
}

FILTER_COLUMNS = {
    "firm": ("text", Job.firm),
    "title": ("text", Job.title),
    "location": ("text", Job.location),
    "practice_area": ("text", Job.practice_area),
    "pqe_level": ("text", Job.pqe_level),
    "status": ("text", Job.status),
    "source_reference": ("text", Job.source_reference),
    "job_url": ("text", Job.job_url),
    "full_description": ("text", Job.full_description),
    "first_seen": ("date", Job.first_seen),
    "last_seen": ("date", Job.last_seen),
    "last_checked": ("date", Job.last_checked),
    "removed_at": ("date", Job.removed_at),
}


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
    first_seen_from: datetime | None = None,
    first_seen_to: datetime | None = None,
    checked_from: datetime | None = None,
    checked_to: datetime | None = None,
    removed_from: datetime | None = None,
    removed_to: datetime | None = None,
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
    if first_seen_from is not None:
        query = query.filter(Job.first_seen >= first_seen_from)
    if first_seen_to is not None:
        query = query.filter(Job.first_seen <= first_seen_to)
    if checked_from is not None:
        query = query.filter(Job.last_checked >= checked_from)
    if checked_to is not None:
        query = query.filter(Job.last_checked <= checked_to)
    if removed_from is not None:
        query = query.filter(Job.removed_at >= removed_from)
    if removed_to is not None:
        query = query.filter(Job.removed_at <= removed_to)
    return query


def _sorted_query(query, sort_by: str | None, sort_direction: str | None):
    column = SORT_COLUMNS.get(sort_by or "last_seen", Job.last_seen)
    direction = (sort_direction or "desc").lower()
    primary = column.asc() if direction == "asc" else column.desc()

    return query.order_by(primary, Job.last_checked.desc(), Job.id.desc())


def _parse_filter_date(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid filter date: {value}") from exc


def _apply_field_filter(query, field: str, operator: str, value: str | None):
    column_info = FILTER_COLUMNS.get(field)
    if column_info is None:
        raise HTTPException(status_code=400, detail=f"Unsupported export filter field: {field}")

    column_type, column = column_info
    normalized_operator = operator.strip().lower()
    normalized_value = (value or "").strip()

    if normalized_operator == "is_empty":
        if column_type == "text":
            return query.filter(or_(column.is_(None), column == ""))
        return query.filter(column.is_(None))

    if normalized_operator == "is_not_empty":
        if column_type == "text":
            return query.filter(and_(column.is_not(None), column != ""))
        return query.filter(column.is_not(None))

    if not normalized_value:
        return query

    if column_type == "date":
        date_value = _parse_filter_date(normalized_value)
        if normalized_operator == "before":
            return query.filter(column < date_value)
        if normalized_operator == "after":
            return query.filter(column > date_value)
        if normalized_operator == "on_or_before":
            return query.filter(column <= date_value)
        if normalized_operator == "on_or_after":
            return query.filter(column >= date_value)
        if normalized_operator == "equals":
            return query.filter(column >= date_value, column < date_value + timedelta(days=1))
        if normalized_operator == "not_equals":
            return query.filter(or_(column < date_value, column >= date_value + timedelta(days=1), column.is_(None)))
        raise HTTPException(status_code=400, detail=f"Unsupported date filter condition: {operator}")

    if normalized_operator == "contains":
        return query.filter(column.ilike(f"%{normalized_value}%"))
    if normalized_operator == "not_contains":
        return query.filter(or_(column.is_(None), ~column.ilike(f"%{normalized_value}%")))
    if normalized_operator == "equals":
        return query.filter(column == normalized_value)
    if normalized_operator == "not_equals":
        return query.filter(or_(column.is_(None), column != normalized_value))
    if normalized_operator == "starts_with":
        return query.filter(column.ilike(f"{normalized_value}%"))
    if normalized_operator == "ends_with":
        return query.filter(column.ilike(f"%{normalized_value}"))

    raise HTTPException(status_code=400, detail=f"Unsupported text filter condition: {operator}")


def _apply_export_filters(
    query,
    statuses: list[str],
    firms: list[str],
    field_filters: str | None,
):
    clean_statuses = [item.upper() for item in statuses if item and item.lower() != "all"]
    clean_firms = [item for item in firms if item and item.lower() != "all"]

    if clean_statuses:
        query = query.filter(Job.status.in_(clean_statuses))
    if clean_firms:
        query = query.filter(or_(Job.firm.in_(clean_firms), Job.firm_key.in_(clean_firms)))
    if not field_filters:
        return query

    try:
        filters = json.loads(field_filters)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid field_filters JSON") from exc

    if not isinstance(filters, list):
        raise HTTPException(status_code=400, detail="field_filters must be a list")

    for item in filters:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Each field filter must be an object")
        query = _apply_field_filter(
            query,
            str(item.get("field") or ""),
            str(item.get("operator") or ""),
            item.get("value"),
        )
    return query


@router.get("", response_model=JobList)
def list_jobs(
    search: str | None = None,
    status: str | None = None,
    firm: str | None = None,
    changed_only: bool = False,
    seen_from: datetime | None = None,
    seen_to: datetime | None = None,
    first_seen_from: datetime | None = None,
    first_seen_to: datetime | None = None,
    checked_from: datetime | None = None,
    checked_to: datetime | None = None,
    removed_from: datetime | None = None,
    removed_to: datetime | None = None,
    sort_by: str | None = Query("last_seen"),
    sort_direction: str | None = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = _sorted_query(
        _filtered_query(
            db,
            search,
            status,
            firm,
            changed_only,
            seen_from,
            seen_to,
            first_seen_from,
            first_seen_to,
            checked_from,
            checked_to,
            removed_from,
            removed_to,
        ),
        sort_by,
        sort_direction,
    )
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
    status: list[str] | None = Query(default=None),
    firm: list[str] | None = Query(default=None),
    changed_only: bool = False,
    seen_from: datetime | None = None,
    seen_to: datetime | None = None,
    first_seen_from: datetime | None = None,
    first_seen_to: datetime | None = None,
    checked_from: datetime | None = None,
    checked_to: datetime | None = None,
    removed_from: datetime | None = None,
    removed_to: datetime | None = None,
    field_filters: str | None = None,
    sort_by: str | None = Query("firm"),
    sort_direction: str | None = Query("asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = _sorted_query(
        _apply_export_filters(
            _filtered_query(
                db,
                search,
                None,
                None,
                changed_only,
                seen_from,
                seen_to,
                first_seen_from,
                first_seen_to,
                checked_from,
                checked_to,
                removed_from,
                removed_to,
            ),
            status or [],
            firm or [],
            field_filters,
        ),
        sort_by,
        sort_direction,
    ).all()
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
