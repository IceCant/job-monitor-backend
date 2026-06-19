import asyncio
import hashlib
from difflib import SequenceMatcher
from datetime import datetime, timezone
from collections import defaultdict
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.models.job_change import JobChange
from app.models.job import Job
from app.models.scrape_run import ScrapeRun
from app.plugins.registry import get_firm_definition, list_firm_definitions
from app.schemas.job_result import JobResult

STATUS_NEW = "NEW"
STATUS_LIVE = "LIVE"
STATUS_UPDATED = "UPDATED"
STATUS_REMOVED = "REMOVED"
STATUS_REPOSTED = "REPOSTED"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"


def _now():
    return datetime.now(timezone.utc)


def _ts():
    return _now().strftime("%H:%M:%S")


async def run_firm(firm, progress_callback: Callable[[dict[str, Any]], None] | None = None):
    """Instantiate the firm's plugin and return a list of JobResult objects."""
    plugin_class = firm.plugin_class
    config = dict(getattr(plugin_class, "default_config", {}) or {})
    kwargs = dict(config)
    if firm.careers_url and "careers_url" not in kwargs:
        kwargs["careers_url"] = firm.careers_url
    if progress_callback is not None:
        kwargs["progress_callback"] = progress_callback
    plugin = plugin_class(
        firm_name=firm.name,
        plugin_config=config,
        **kwargs,
    )

    raw_results = await plugin.scrape()
    return _normalize_results(raw_results)


def _normalize_results(results: list[Any]) -> list[JobResult]:
    normalized: list[JobResult] = []
    for item in results:
        if isinstance(item, JobResult):
            normalized.append(item)
            continue

        if isinstance(item, dict):
            normalized.append(JobResult(**item))
            continue

        raise ValueError(
            "Plugin scrape() must return list[JobResult] or list[dict] with JobResult fields"
        )

    return normalized


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlsplit(url.strip())
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def _similarity_key(title: str | None, location: str | None, practice_area: str | None) -> str | None:
    title_text = _normalize_text(title)
    location_text = _normalize_text(location)
    practice_text = _normalize_text(practice_area)
    if not title_text:
        return None
    payload = "|".join([title_text.lower(), location_text.lower(), practice_text.lower()])
    return f"sig:{payload}"


def _location_practice_key(location: str | None, practice_area: str | None) -> str | None:
    location_text = _normalize_text(location)
    practice_text = _normalize_text(practice_area)
    if not location_text and not practice_text:
        return None
    return f"lp:{location_text.lower()}|{practice_text.lower()}"


def _match_key(job_url: str | None, source_reference: str | None, similarity: str | None, fallback_payload: str) -> str:
    if source_reference:
        return f"ref:{source_reference.lower()}"
    if job_url:
        return f"url:{job_url}"
    if similarity:
        return similarity
    digest = hashlib.sha1(fallback_payload.encode("utf-8")).hexdigest()[:16]
    return f"fallback:{digest}"


def _history_entry(
    now: datetime,
    event: str,
    message: str | None = None,
    changed_fields: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "timestamp": now.isoformat(),
        "event": event,
        "message": message,
        "changed_fields": changed_fields or {},
        "snapshot": snapshot or {},
    }


def _append_history(job: Job, entry: dict[str, Any]) -> None:
    history = list(job.change_history or [])
    history.append(entry)
    job.change_history = history


def _append_history_row(db: Session, job: Job, entry: dict[str, Any]) -> None:
    if job.id is None:
        return
    changed_at = datetime.fromisoformat(entry["timestamp"])
    db.add(
        JobChange(
            job_id=job.id,
            firm_key=job.firm_key or "unknown",
            changed_at=changed_at,
            event=entry.get("event") or STATUS_NEEDS_REVIEW,
            message=entry.get("message"),
            changed_fields=entry.get("changed_fields") or {},
            snapshot=entry.get("snapshot") or {},
        )
    )


def _record_history(db: Session, job: Job, entry: dict[str, Any]) -> None:
    _append_history(job, entry)
    _append_history_row(db, job, entry)


def _create_scrape_run(
    db: Session,
    *,
    firm_key: str | None,
    firm_label: str,
    started_at: datetime,
    status: str,
    jobs_found: int,
    errors: int,
    logs: list[str],
    error_message: str | None = None,
) -> ScrapeRun:
    payload: dict[str, Any] = {
        "firm": firm_label,
        "started_at": started_at,
        "finished_at": _now(),
        "status": status,
        "jobs_found": jobs_found,
        "errors": errors,
        "logs": logs,
    }
    if firm_key is not None:
        payload["firm_key"] = firm_key
    if error_message is not None:
        payload["error_message"] = error_message

    run = ScrapeRun(**payload)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _job_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": data.get("title"),
        "location": data.get("location"),
        "practice_area": data.get("practice_area"),
        "pqe_level": data.get("pqe_level"),
        "job_url": data.get("job_url"),
        "source_reference": data.get("source_reference"),
        "status": data.get("status"),
    }


def _prepare_result(firm, result: JobResult) -> dict[str, Any]:
    extra = dict(result.extra_info or {})
    title = _normalize_text(result.title or extra.get("title")) or None
    location = _normalize_text(result.office_location) or None
    practice_area = _normalize_text(result.practice_area) or None
    pqe_level = _normalize_text(result.pqe_level) or None
    description = _normalize_text(result.description or extra.get("description")) or None
    job_url = _normalize_url(result.job_url)
    source_reference = _normalize_text(result.source_reference or extra.get("job_id") or extra.get("reference")) or None
    similarity = _similarity_key(title, location, practice_area)
    fallback_payload = "|".join(
        [
            firm.key,
            title or "",
            location or "",
            practice_area or "",
            pqe_level or "",
            description or "",
            str(extra),
        ]
    )
    match_key = _match_key(job_url, source_reference, similarity, fallback_payload)

    issues: list[str] = []
    if not title:
        issues.append("Missing title")
    if not job_url and not source_reference:
        issues.append("Missing both job URL and reference number")
    if not location:
        issues.append("Missing location")

    return {
        "firm_key": firm.key,
        "firm": firm.name,
        "title": title,
        "location": location,
        "practice_area": practice_area,
        "pqe_level": pqe_level,
        "job_url": job_url,
        "source_reference": source_reference,
        "first_seen": None,
        "last_seen": None,
        "last_checked": None,
        "removed_at": None,
        "full_description": description,
        "extra_info": extra,
        "similarity_key": similarity,
        "match_key": match_key,
        "issues": issues,
    }


def _build_indexes(existing_jobs: list[Job]) -> dict[str, Any]:
    by_url: dict[str, list[Job]] = defaultdict(list)
    by_ref: dict[str, list[Job]] = defaultdict(list)
    by_similarity: dict[str, list[Job]] = defaultdict(list)
    by_location_practice: dict[str, list[Job]] = defaultdict(list)
    by_id = {job.id: job for job in existing_jobs if job.id is not None}

    for job in existing_jobs:
        normalized_url = _normalize_url(job.job_url)
        if normalized_url:
            by_url[normalized_url].append(job)
        ref = _normalize_text(job.source_reference)
        if ref:
            by_ref[ref.lower()].append(job)
        similarity = _similarity_key(job.title, job.location, job.practice_area)
        if similarity:
            by_similarity[similarity].append(job)
        location_practice = _location_practice_key(job.location, job.practice_area)
        if location_practice:
            by_location_practice[location_practice].append(job)

    return {
        "by_url": by_url,
        "by_ref": by_ref,
        "by_similarity": by_similarity,
        "by_location_practice": by_location_practice,
        "by_id": by_id,
    }


def _pick_match(
    indexes: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[Job | None, list[str]]:
    issues: list[str] = []

    job_url = candidate["job_url"]
    source_reference = candidate["source_reference"]
    similarity = candidate["similarity_key"]

    # When the scraped result has a reference number,
    # only the same reference may represent the same job.
    if source_reference:
        matches = indexes["by_ref"].get(
            source_reference.lower(),
            [],
        )

        if len(matches) == 1:
            return matches[0], issues

        if len(matches) > 1:
            issues.append(
                "Multiple existing jobs share this reference number"
            )
            return None, issues

        # Important:
        # A new reference means a different job.
        # Do not fall back to a shared URL or similar title.
        return None, issues

    # Only use URL matching when no reference number is available.
    if job_url:
        matches = indexes["by_url"].get(job_url, [])

        if len(matches) == 1:
            return matches[0], issues

        if len(matches) > 1:
            issues.append(
                "Multiple existing jobs share this URL"
            )

    if similarity:
        matches = indexes["by_similarity"].get(
            similarity,
            [],
        )

        if len(matches) == 1:
            issues.append(
                "Matched by similar title/location/practice area"
            )
            return matches[0], issues

        if len(matches) > 1:
            issues.append(
                "Similar title/location matched multiple jobs"
            )

    location_practice = _location_practice_key(
        candidate["location"],
        candidate["practice_area"],
    )

    if location_practice and candidate["title"]:
        fuzzy_matches: list[Job] = []

        for job in indexes["by_location_practice"].get(
            location_practice,
            [],
        ):
            if not job.title:
                continue

            ratio = SequenceMatcher(
                None,
                job.title.lower(),
                candidate["title"].lower(),
            ).ratio()

            if ratio >= 0.82:
                fuzzy_matches.append(job)

        if len(fuzzy_matches) == 1:
            issues.append(
                "Matched by similar title with same location/practice area"
            )
            return fuzzy_matches[0], issues

        if len(fuzzy_matches) > 1:
            issues.append(
                "Fuzzy title match found multiple candidate jobs"
            )

    return None, issues

def _changed_fields(job: Job, candidate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    changed: dict[str, dict[str, Any]] = {}
    fields = {
        "title": candidate["title"],
        "location": candidate["location"],
        "practice_area": candidate["practice_area"],
        "pqe_level": candidate["pqe_level"],
        "job_url": candidate["job_url"],
        "source_reference": candidate["source_reference"],
        "full_description": candidate["full_description"],
    }
    for field, new_value in fields.items():
        if getattr(job, field) != new_value:
            changed[field] = {"from": getattr(job, field), "to": new_value}
    return changed


def _major_change_needs_review(
    job: Job,
    candidate: dict[str, Any],
    changed_fields: dict[str, Any],
) -> bool:
    # Different non-empty references mean these should not
    # have been matched as the same job.
    if (
        job.source_reference
        and candidate["source_reference"]
        and job.source_reference.lower()
        != candidate["source_reference"].lower()
    ):
        return True

    if "job_url" in changed_fields and job.job_url:
        return True

    if len(changed_fields) >= 3:
        return True

    if "title" in changed_fields and job.title and candidate["title"]:
        ratio = SequenceMatcher(
            None,
            job.title.lower(),
            candidate["title"].lower(),
        ).ratio()

        if ratio < 0.55:
            return True

    return False


def persist_scrape(db: Session, firm, results) -> dict:
    """Persist one firm scrape with O(existing + scraped) matching and history."""
    now = _now()
    counts = {
        "new": 0,
        "updated": 0,
        "live": 0,
        "removed": 0,
        "reposted": 0,
        "needs_review": 0,
    }

    existing_jobs: list[Job] = list(db.query(Job).filter(Job.firm_key == firm.key).all())
    active_before = [job for job in existing_jobs if job.status != STATUS_REMOVED]
    if active_before and not results:
        raise ValueError("Scrape returned no jobs; removals skipped because the result looks suspicious")

    indexes = _build_indexes(existing_jobs)
    touched_ids: set[int] = set()
    processed_match_keys: dict[str, int] = {}

    prepared = [_prepare_result(firm, result) for result in results]
    duplicate_counts: dict[str, int] = defaultdict(int)
    for item in prepared:
        duplicate_counts[item["match_key"]] += 1
    for item in prepared:
        if duplicate_counts[item["match_key"]] > 1:
            item["issues"].append("Duplicate match key appeared more than once in this scrape")

    for candidate in prepared:
        matched_job, match_issues = _pick_match(indexes, candidate)
        issues = list(candidate["issues"]) + match_issues

        if candidate["match_key"] in processed_match_keys:
            matched_existing = indexes["by_id"].get(processed_match_keys[candidate["match_key"]])
            if matched_existing is not None:
                matched_existing.status = STATUS_NEEDS_REVIEW
                matched_existing.last_checked = now
                matched_existing.last_seen = now
                _record_history(
                    db,
                    matched_existing,
                    _history_entry(
                        now,
                        STATUS_NEEDS_REVIEW,
                        message="Duplicate rows appeared in the same scrape; manual review needed",
                    ),
                )
                counts["needs_review"] += 1
                if matched_existing.id is not None:
                    touched_ids.add(matched_existing.id)
            continue

        if matched_job is None:
            status = STATUS_NEEDS_REVIEW if issues else STATUS_NEW
            new_job = Job(
                firm_key=firm.key,
                firm=firm.name,
                title=candidate["title"],
                location=candidate["location"],
                practice_area=candidate["practice_area"],
                pqe_level=candidate["pqe_level"],
                status=status,
                job_url=candidate["job_url"],
                match_key=candidate["match_key"],
                source_reference=candidate["source_reference"],
                first_seen=now,
                last_seen=now,
                last_checked=now,
                full_description=candidate["full_description"],
                change_history=[],
                extra_info=candidate["extra_info"],
            )
            entry = _history_entry(
                now,
                status,
                message="New job found" if status == STATUS_NEW else "; ".join(issues),
                snapshot=_job_snapshot({**candidate, "status": status}),
            )
            db.add(new_job)
            db.flush()
            _record_history(db, new_job, entry)
            indexes["by_id"][new_job.id] = new_job
            if candidate["job_url"]:
                indexes["by_url"][candidate["job_url"]].append(new_job)
            if candidate["source_reference"]:
                indexes["by_ref"][candidate["source_reference"].lower()].append(new_job)
            if candidate["similarity_key"]:
                indexes["by_similarity"][candidate["similarity_key"]].append(new_job)
            if new_job.id is not None:
                touched_ids.add(new_job.id)
                processed_match_keys[candidate["match_key"]] = new_job.id
            if status == STATUS_NEW:
                counts["new"] += 1
            else:
                counts["needs_review"] += 1
            continue

        changed = _changed_fields(matched_job, candidate)
        if matched_job.status == STATUS_REMOVED:
            status = STATUS_REPOSTED
            message = "Job was previously removed and has reappeared"
        elif issues or _major_change_needs_review(matched_job, candidate, changed):
            status = STATUS_NEEDS_REVIEW
            message = "; ".join(issues or ["Significant job data change requires review"])
        elif changed:
            status = STATUS_UPDATED
            message = "Job details changed"
        else:
            status = STATUS_LIVE
            message = None

        matched_job.firm = firm.name
        matched_job.firm_key = firm.key
        matched_job.title = candidate["title"]
        matched_job.location = candidate["location"]
        matched_job.practice_area = candidate["practice_area"]
        matched_job.pqe_level = candidate["pqe_level"]
        matched_job.job_url = candidate["job_url"]
        matched_job.match_key = candidate["match_key"]
        matched_job.source_reference = candidate["source_reference"]
        matched_job.last_seen = now
        matched_job.last_checked = now
        matched_job.removed_at = None
        matched_job.full_description = candidate["full_description"]
        matched_job.extra_info = candidate["extra_info"]
        matched_job.status = status

        if status != STATUS_LIVE:
            _record_history(
                db,
                matched_job,
                _history_entry(
                    now,
                    status,
                    message=message,
                    changed_fields=changed,
                    snapshot=_job_snapshot({**candidate, "status": status}),
                ),
            )

        if matched_job.id is not None:
            touched_ids.add(matched_job.id)
            processed_match_keys[candidate["match_key"]] = matched_job.id

        if status == STATUS_UPDATED:
            counts["updated"] += 1
        elif status == STATUS_REPOSTED:
            counts["reposted"] += 1
        elif status == STATUS_NEEDS_REVIEW:
            counts["needs_review"] += 1
        else:
            counts["live"] += 1

    for job in active_before:
        if job.id in touched_ids:
            continue
        job.status = STATUS_REMOVED
        job.last_checked = now
        job.removed_at = now
        _record_history(
            db,
            job,
            _history_entry(
                now,
                STATUS_REMOVED,
                message="Job no longer found in a successful scrape",
                snapshot=_job_snapshot(
                    {
                        "title": job.title,
                        "location": job.location,
                        "practice_area": job.practice_area,
                        "pqe_level": job.pqe_level,
                        "job_url": job.job_url,
                        "source_reference": job.source_reference,
                        "status": STATUS_REMOVED,
                    }
                ),
            ),
        )
        counts["removed"] += 1

    db.commit()
    return counts


ProgressCallback = Callable[[dict[str, Any]], None]


def run_scrape(
    db: Session,
    firm_key: str | None = None,
    include_disabled: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> ScrapeRun:
    """Scrape one firm or all enabled firm plugins; record a ScrapeRun and return it.

    A single firm failing degrades the run to ``partial`` rather than raising.
    """
    if firm_key is not None:
        firms = [get_firm_definition(firm_key)]
        label = firms[0].name
    else:
        firms = list_firm_definitions(include_disabled=include_disabled)
        if not include_disabled:
            firms = [firm for firm in firms if firm.enabled]
        label = "All Firms"

    if not firms:
        raise ValueError("No firm plugins are enabled")

    started = _now()
    logs: list[str] = [f"[{_ts()}] Starting scrape for {label}..."]
    total_found = 0
    errors = 0
    first_error: str | None = None
    last_run: ScrapeRun | None = None

    if progress_callback:
        progress_callback(
            {
                "status": "running",
                "label": label,
                "total_firms": len(firms),
                "completed_firms": 0,
                "percent": 5,
                "current_firm_percent": 0,
                "current_firm_stage": "Queued",
                "message": f"Starting scrape for {label}...",
                "logs": logs,
            }
        )

    for index, f in enumerate(firms):
        firm_started = _now()
        firm_logs = [f"[{_ts()}] Starting scrape for {f.name}..."]
        if progress_callback:
            progress_callback(
                {
                    "status": "running",
                    "label": label,
                    "current_firm": f.name,
                    "total_firms": len(firms),
                    "completed_firms": index,
                    "percent": max(5, round((index / len(firms)) * 100)),
                    "current_firm_percent": 15,
                    "current_firm_stage": "Scraping",
                    "jobs_found": total_found,
                    "errors": errors,
                    "message": f"Scraping {f.name}...",
                    "logs": logs + firm_logs,
                }
            )
        try:
            def on_plugin_progress(payload: dict[str, Any]) -> None:
                if not progress_callback:
                    return
                firm_percent = max(15, min(70, int(payload.get("current_firm_percent", 15))))
                progress_callback(
                    {
                        "status": "running",
                        "label": label,
                        "current_firm": f.name,
                        "total_firms": len(firms),
                        "completed_firms": index,
                        "percent": max(
                            5,
                            round(((index + (firm_percent / 100 * 0.7)) / len(firms)) * 100),
                        ),
                        "current_firm_percent": firm_percent,
                        "current_firm_stage": payload.get("current_firm_stage") or "Scraping",
                        "jobs_found": total_found + int(payload.get("jobs_seen", 0) or 0),
                        "errors": errors,
                        "message": payload.get("message") or f"Scraping {f.name}...",
                        "logs": logs + firm_logs + list(payload.get("logs") or []),
                    }
                )

            results = asyncio.run(run_firm(f, progress_callback=on_plugin_progress))
            if progress_callback:
                progress_callback(
                    {
                        "status": "running",
                        "label": label,
                        "current_firm": f.name,
                        "total_firms": len(firms),
                        "completed_firms": index,
                        "percent": max(10, round(((index + 0.6) / len(firms)) * 100)),
                        "current_firm_percent": 75,
                        "current_firm_stage": "Saving results",
                        "jobs_found": total_found,
                        "errors": errors,
                        "message": f"Saving {f.name} results...",
                        "logs": logs + firm_logs,
                    }
                )
            counts = persist_scrape(db, f, results)
            total_found += len(results)
            message = (
                f"[{_ts()}] {f.name}: {len(results)} jobs "
                f"({counts['new']} new, {counts['updated']} updated, "
                f"{counts['reposted']} reposted, {counts['needs_review']} needs review, "
                f"{counts['removed']} removed)"
            )
            firm_logs.append(message)
            logs.append(message)
            last_run = _create_scrape_run(
                db,
                firm_key=f.key,
                firm_label=f.name,
                started_at=firm_started,
                status="success",
                jobs_found=len(results),
                errors=0,
                logs=firm_logs + [f"[{_ts()}] Scrape completed successfully"],
            )
            if progress_callback:
                progress_callback(
                    {
                        "status": "running",
                        "label": label,
                        "current_firm": f.name,
                        "total_firms": len(firms),
                        "completed_firms": index + 1,
                        "percent": round(((index + 1) / len(firms)) * 100),
                        "current_firm_percent": 100,
                        "current_firm_stage": "Complete",
                        "jobs_found": total_found,
                        "errors": errors,
                        "message": message,
                        "logs": logs,
                    }
                )
        except Exception as exc:  # noqa: BLE001 - record, don't crash the run
            errors += 1
            if first_error is None:
                first_error = str(exc)
            error_message = f"[{_ts()}] ERROR: {f.name} - {exc}"
            firm_logs.append(error_message)
            logs.append(error_message)
            last_run = _create_scrape_run(
                db,
                firm_key=f.key,
                firm_label=f.name,
                started_at=firm_started,
                status="failed",
                jobs_found=0,
                errors=1,
                logs=firm_logs,
                error_message=str(exc),
            )
            if progress_callback:
                progress_callback(
                    {
                        "status": "running",
                        "label": label,
                        "current_firm": f.name,
                        "total_firms": len(firms),
                        "completed_firms": index + 1,
                        "percent": round(((index + 1) / len(firms)) * 100),
                        "current_firm_percent": 100,
                        "current_firm_stage": "Failed",
                        "jobs_found": total_found,
                        "errors": errors,
                        "message": error_message,
                        "logs": logs,
                    }
                )

    if errors == 0:
        status = "success"
        logs.append(f"[{_ts()}] Scrape completed successfully")
    elif errors == len(firms):
        status = "failed"
        logs.append(f"[{_ts()}] Scrape failed")
    else:
        status = "partial"
        logs.append(f"[{_ts()}] Scrape completed with errors")

    if len(firms) == 1 and last_run is not None:
        if progress_callback:
            progress_callback(
                {
                    "status": status,
                    "label": label,
                    "current_firm": firms[0].name,
                    "total_firms": len(firms),
                    "completed_firms": len(firms),
                    "percent": 100,
                    "current_firm_percent": 100,
                    "current_firm_stage": "Complete" if status == "success" else status.title(),
                    "jobs_found": total_found if total_found else last_run.jobs_found,
                    "errors": errors,
                    "message": logs[-1] if logs else "Scrape finished",
                    "logs": logs,
                }
            )
        return last_run

    run = _create_scrape_run(
        db,
        firm_key=None,
        firm_label=label,
        started_at=started,
        status=status,
        jobs_found=total_found,
        errors=errors,
        logs=logs,
        error_message=first_error,
    )
    if progress_callback:
        progress_callback(
            {
                "status": status,
                "label": label,
                "current_firm": None,
                "total_firms": len(firms),
                "completed_firms": len(firms),
                "percent": 100,
                "current_firm_percent": 100,
                "current_firm_stage": "Complete" if status == "success" else status.title(),
                "jobs_found": total_found,
                "errors": errors,
                "message": logs[-1] if logs else "Scrape finished",
                "logs": logs,
            }
        )
    return run
