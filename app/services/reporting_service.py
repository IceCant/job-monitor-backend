from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.scrape_run import ScrapeRun


def job_status_counts_by_firm(
    db: Session, firm_keys: list[str]
) -> dict[str, dict[str, int]]:
    if not firm_keys:
        return {}

    counts: dict[str, dict[str, int]] = defaultdict(dict)
    rows = (
        db.query(Job.firm_key, Job.status, func.count(Job.id))
        .filter(Job.firm_key.in_(firm_keys))
        .group_by(Job.firm_key, Job.status)
        .all()
    )
    for firm_key, status, count in rows:
        if firm_key:
            counts[firm_key][status or "UNKNOWN"] = count
    return dict(counts)


def latest_runs_by_firm(
    db: Session, firm_keys: list[str]
) -> dict[str, ScrapeRun]:
    if not firm_keys:
        return {}

    ranked = (
        db.query(
            ScrapeRun.id.label("run_id"),
            func.row_number()
            .over(
                partition_by=ScrapeRun.firm_key,
                order_by=(ScrapeRun.started_at.desc(), ScrapeRun.id.desc()),
            )
            .label("position"),
        )
        .filter(ScrapeRun.firm_key.in_(firm_keys))
        .subquery()
    )
    rows = (
        db.query(ScrapeRun)
        .join(ranked, ScrapeRun.id == ranked.c.run_id)
        .filter(ranked.c.position == 1)
        .all()
    )
    return {row.firm_key: row for row in rows if row.firm_key}
