import asyncio
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.scrape_run import ScrapeRun
from app.plugins.registry import PLUGIN_MAP


def _now():
    return datetime.now(timezone.utc)


def _ts():
    return _now().strftime("%H:%M:%S")


async def run_firm(firm):
    """Instantiate the firm's plugin and return a list of JobResult objects."""
    plugin_class = PLUGIN_MAP[firm.plugin]

    config = firm.plugin_config or {}
    plugin = plugin_class(
        firm_name=firm.name,
        api_url=config["api_url"],
        careers_url=config["careers_url"],
        max_pages=config.get("max_pages"),
    )

    return await plugin.scrape()


def persist_scrape(db: Session, firm, results) -> dict:
    """Upsert scraped jobs for a firm and flag NEW / UPDATED / LIVE / REMOVED.

    Dedupes by ``job_url``. URLs previously seen for this firm but absent from
    the latest results are marked ``REMOVED``. Returns counts by bucket.
    """
    now = _now()
    counts = {"new": 0, "updated": 0, "live": 0, "removed": 0}

    seen_urls = set()
    for r in results:
        seen_urls.add(r.job_url)
        title = (r.extra_info or {}).get("title")
        existing = db.query(Job).filter(Job.job_url == r.job_url).first()

        if existing is None:
            db.add(
                Job(
                    firm_id=getattr(firm, "id", None),
                    firm=r.firm_name,
                    title=title,
                    location=r.office_location,
                    practice_area=r.practice_area,
                    pqe_level=r.pqe_level,
                    status="NEW",
                    job_url=r.job_url,
                    first_seen=now,
                    last_checked=now,
                    extra_info=r.extra_info,
                )
            )
            counts["new"] += 1
        else:
            changed = (
                existing.title != title
                or existing.location != r.office_location
                or existing.status == "REMOVED"
            )
            existing.title = title
            existing.location = r.office_location
            existing.practice_area = r.practice_area
            existing.pqe_level = r.pqe_level
            existing.extra_info = r.extra_info
            existing.last_checked = now
            existing.firm_id = getattr(firm, "id", None)
            if changed:
                existing.status = "UPDATED"
                counts["updated"] += 1
            else:
                existing.status = "LIVE"
                counts["live"] += 1

    # Anything we have for this firm that wasn't in the latest pull is gone.
    firm_id = getattr(firm, "id", None)
    if firm_id is not None:
        stale = (
            db.query(Job)
            .filter(Job.firm_id == firm_id, Job.status != "REMOVED")
            .all()
        )
        for job in stale:
            if job.job_url not in seen_urls:
                job.status = "REMOVED"
                job.last_checked = now
                counts["removed"] += 1

    db.commit()
    return counts


def run_scrape(db: Session, firm=None) -> ScrapeRun:
    """Scrape one firm or all active firms; record a ScrapeRun and return it.

    A single firm failing degrades the run to ``partial`` rather than raising.
    """
    from app.models.firm import Firm

    if firm is not None:
        firms = [firm]
        label = firm.name
    else:
        firms = db.query(Firm).filter(Firm.active.is_(True)).all()
        label = "All Firms"

    started = _now()
    logs: list[str] = [f"[{_ts()}] Starting scrape for {label}..."]
    total_found = 0
    errors = 0

    for f in firms:
        try:
            results = asyncio.run(run_firm(f))
            counts = persist_scrape(db, f, results)
            total_found += len(results)
            logs.append(
                f"[{_ts()}] {f.name}: {len(results)} jobs "
                f"({counts['new']} new, {counts['updated']} updated, "
                f"{counts['removed']} removed)"
            )
            f.last_run_at = _now()
            f.last_run_status = "success"
        except Exception as exc:  # noqa: BLE001 - record, don't crash the run
            errors += 1
            logs.append(f"[{_ts()}] ERROR: {f.name} - {exc}")
            f.last_run_at = _now()
            f.last_run_status = "failed"
        db.commit()

    if errors == 0:
        status = "success"
        logs.append(f"[{_ts()}] Scrape completed successfully")
    elif errors == len(firms):
        status = "failed"
        logs.append(f"[{_ts()}] Scrape failed")
    else:
        status = "partial"
        logs.append(f"[{_ts()}] Scrape completed with errors")

    run = ScrapeRun(
        firm=label,
        started_at=started,
        finished_at=_now(),
        status=status,
        jobs_found=total_found,
        errors=errors,
        logs=logs,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run
