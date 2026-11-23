"""In-memory status registry for long-running tasks (MVP, single worker)."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

_TASKS: dict[str, dict] = {}
_LOCK = threading.Lock()


def new_task(kind: str, params: dict | None = None) -> str:
    task_id = uuid.uuid4().hex
    with _LOCK:
        _TASKS[task_id] = {
            "id": task_id,
            "kind": kind,
            "status": "running",
            "params": params or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "result": None,
            "error": None,
        }
    return task_id


def set_result(task_id: str, result: dict) -> None:
    with _LOCK:
        if task_id in _TASKS:
            _TASKS[task_id].update(
                status="success", result=result,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )


def set_error(task_id: str, error: str) -> None:
    with _LOCK:
        if task_id in _TASKS:
            _TASKS[task_id].update(
                status="failed", error=error,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )


def get_task(task_id: str) -> dict | None:
    with _LOCK:
        return dict(_TASKS[task_id]) if task_id in _TASKS else None


def list_tasks(limit: int = 20) -> list[dict]:
    with _LOCK:
        items = sorted(_TASKS.values(), key=lambda t: t["created_at"], reverse=True)
        return items[:limit]


def latest_task() -> dict | None:
    items = list_tasks(1)
    return items[0] if items else None
