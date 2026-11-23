"""Lightweight periodic scheduler (no external dependency).

Runs inside the FastAPI process. For multi-worker deployments, move these jobs
to a separate worker process later; the task functions are already isolated.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.config import settings

from . import state
from .tasks import run_analysis, run_auto_publish, run_link_check, run_report, run_research

_TASK: asyncio.Task | None = None
_PUBLISH_TASK: asyncio.Task | None = None

DAILY = 24 * 3600
WEEKLY = 7 * DAILY


async def _safe(name: str, coro) -> None:
    task_id = state.new_task(name)
    try:
        state.set_result(task_id, await coro)
    except Exception as exc:
        state.set_error(task_id, f"{type(exc).__name__}: {exc}")


async def _loop() -> None:
    # Small startup delay so the web server becomes healthy first.
    await asyncio.sleep(10)
    # Negative offsets make the first daily/weekly cycle run immediately after
    # the startup delay instead of waiting a full 24 hours.
    last_daily = -DAILY
    last_weekly = -WEEKLY
    loop = asyncio.get_running_loop()
    while True:
        now = loop.time()
        if now - last_daily >= DAILY:
            await _safe("scheduled_collection", run_research("all", {"limit": 25}))
            await _safe("scheduled_analysis", run_analysis(limit=100))
            await _safe("scheduled_link_check", run_link_check())
            last_daily = now
        if now - last_weekly >= WEEKLY:
            await _safe("scheduled_report", run_report(days=30))
            last_weekly = now
        await asyncio.sleep(DAILY)


async def _publish_loop() -> None:
    """Short-interval loop for the auto-publish queue."""
    await asyncio.sleep(15)
    while True:
        if settings.auto_publish_enabled:
            await _safe("auto_publish", run_auto_publish())
        await asyncio.sleep(settings.auto_publish_interval_seconds)


async def start_scheduler() -> None:
    global _TASK, _PUBLISH_TASK
    if settings.scheduler_enabled and _TASK is None:
        _TASK = asyncio.create_task(_loop())
    if settings.auto_publish_enabled and _PUBLISH_TASK is None:
        _PUBLISH_TASK = asyncio.create_task(_publish_loop())


async def stop_scheduler() -> None:
    global _TASK, _PUBLISH_TASK
    for task in (_TASK, _PUBLISH_TASK):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    _TASK = None
    _PUBLISH_TASK = None


def scheduler_status() -> dict:
    return {
        "enabled": settings.scheduler_enabled,
        "running": _TASK is not None and not _TASK.done(),
        "auto_publish": {
            "enabled": settings.auto_publish_enabled,
            "running": _PUBLISH_TASK is not None and not _PUBLISH_TASK.done(),
            "require_approval": settings.auto_publish_require_approval,
            "interval_seconds": settings.auto_publish_interval_seconds,
            "batch_size": settings.auto_publish_batch_size,
            "threads_configured": bool(settings.threads_access_token),
        },
        "last_run": datetime.now(timezone.utc).isoformat(),
    }
