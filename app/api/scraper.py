import json
import os
import time
import asyncio
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database import SessionLocal, get_db
from app.models.scrape_run import ScrapeRun
from app.models.user import User
from app.plugins.registry import get_firm_definition, list_plugins
from app.schemas.api import (
    PluginOut,
    PluginTestOut,
    PluginTestRequest,
    RunRequest,
    ScheduleSettingsOut,
    ScheduleSettingsUpdate,
    ScrapeRunList,
    ScrapeRunOut,
    ScrapeProgressOut,
    ScrapeStartOut,
)
from app.services.scheduler_service import scheduler_service
from app.services.scraper_service import run_scrape

router = APIRouter()

_progress_lock = Lock()
_progress_runs: dict[str, dict] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _update_progress(run_id: str, **updates) -> None:
    with _progress_lock:
        current = _progress_runs.get(run_id)
        if not current:
            return
        current.update(updates)
        current["updated_at"] = _now()
        current["logs"] = (current.get("logs") or [])[-25:]


def _create_progress_run(run_id: str, *, label: str, firm_key: str | None) -> None:
    now = _now()
    with _progress_lock:
        _progress_runs[run_id] = {
            "run_id": run_id,
            "status": "queued",
            "label": label,
            "firm_key": firm_key,
            "current_firm": None,
            "current_firm_percent": 0,
            "current_firm_stage": None,
            "total_firms": 0,
            "completed_firms": 0,
            "percent": 0,
            "jobs_found": 0,
            "errors": 0,
            "message": "Queued",
            "logs": [],
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
        }


def _dev_tools_enabled(hostname: str | None) -> bool:
    env = (
        os.getenv("APP_ENV")
        or os.getenv("ENVIRONMENT")
        or os.getenv("FASTAPI_ENV")
        or ""
    ).lower()
    if env in {"dev", "development", "local", "test"}:
        return True
    if env in {"prod", "production", "staging"}:
        return False
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _ensure_dev_tools_enabled(request: Request) -> None:
    if not _dev_tools_enabled(request.url.hostname):
        raise HTTPException(status_code=404, detail="Not found")


def _to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if is_dataclass(item):
        return asdict(item)
    if hasattr(item, "__dict__"):
        return dict(item.__dict__)
    return {"value": str(item)}


def _create_plugin_for_test(body: PluginTestRequest):
    try:
        firm = get_firm_definition(body.plugin_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    plugin_class = firm.plugin_class
    config = dict(plugin_class.default_config or {})
    config.update(body.config or {})
    kwargs = dict(config)
    if firm.careers_url and "careers_url" not in kwargs:
        kwargs["careers_url"] = firm.careers_url

    return firm, plugin_class(
        firm_name=body.firm_name or firm.name,
        plugin_config=config,
        **kwargs,
    )


def _run_scrape_background(run_id: str, firm_key: str | None, include_disabled: bool) -> None:
    db = SessionLocal()
    try:
        def on_progress(payload: dict) -> None:
            _update_progress(run_id, **payload)

        run_scrape(
            db,
            firm_key=firm_key,
            include_disabled=include_disabled,
            progress_callback=on_progress,
        )
        with _progress_lock:
            current = _progress_runs.get(run_id)
            if current:
                current["finished_at"] = _now()
    except Exception as exc:  # noqa: BLE001 - surface unexpected startup failures to the progress UI
        _update_progress(
            run_id,
            status="failed",
            percent=100,
            errors=1,
            message=str(exc),
            logs=[f"ERROR: {exc}"],
        )
        with _progress_lock:
            current = _progress_runs.get(run_id)
            if current:
                current["finished_at"] = _now()
    finally:
        db.close()


@router.get("/plugins", response_model=list[PluginOut])
def get_plugins(current_user: User = Depends(get_current_user)):
    return [PluginOut(**p) for p in list_plugins()]


@router.post("/dev/test-plugin", response_model=PluginTestOut)
async def test_plugin(
    body: PluginTestRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    _ensure_dev_tools_enabled(request)
    start = time.perf_counter()
    firm, plugin = _create_plugin_for_test(body)
    raw_results = await plugin.scrape()
    results = [_to_dict(item) for item in raw_results]
    preview = results[: body.limit]
    return PluginTestOut(
        plugin_key=firm.key,
        firm_name=body.firm_name or firm.name,
        count=len(results),
        elapsed_ms=round((time.perf_counter() - start) * 1000),
        items=preview,
        raw_json=json.dumps(preview, ensure_ascii=False, indent=2, default=str),
    )


@router.post("/run", response_model=ScrapeStartOut, status_code=status.HTTP_202_ACCEPTED)
def run(
    body: RunRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    if body.firm_key is None:
        run_id = str(uuid4())
        _create_progress_run(run_id, label="All Firms", firm_key=None)
        background_tasks.add_task(_run_scrape_background, run_id, None, False)
        return ScrapeStartOut(
            message="Scrape started for all enabled firms.",
            run_id=run_id,
        )

    try:
        firm = get_firm_definition(body.firm_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    run_id = str(uuid4())
    _create_progress_run(run_id, label=firm.name, firm_key=body.firm_key)
    background_tasks.add_task(_run_scrape_background, run_id, body.firm_key, True)
    return ScrapeStartOut(
        message=f"Scrape started for {firm.name}.",
        run_id=run_id,
        firm_key=body.firm_key,
    )


@router.get("/progress/{run_id}", response_model=ScrapeProgressOut)
def get_progress(run_id: str, current_user: User = Depends(get_current_user)):
    with _progress_lock:
        progress = _progress_runs.get(run_id)
        if progress is None:
            raise HTTPException(status_code=404, detail="Scrape progress not found")
        return ScrapeProgressOut(**progress)


@router.get("/progress/{run_id}/stream")
async def stream_progress(
    run_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    with _progress_lock:
        if run_id not in _progress_runs:
            raise HTTPException(status_code=404, detail="Scrape progress not found")

    async def event_stream():
        last_payload: str | None = None
        while True:
            if await request.is_disconnected():
                break

            with _progress_lock:
                progress = _progress_runs.get(run_id)

            if progress is None:
                yield "event: error\ndata: {\"detail\":\"Scrape progress not found\"}\n\n"
                break

            payload = json.dumps(
                ScrapeProgressOut(**progress).model_dump(mode="json"),
                ensure_ascii=False,
            )
            if payload != last_payload:
                yield f"data: {payload}\n\n"
                last_payload = payload

            if progress.get("status") in {"success", "failed", "partial"}:
                break

            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
