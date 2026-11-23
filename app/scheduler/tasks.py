"""Background task implementations. Each task owns its own DB session."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.ai.tasks import analyze_batch, needs_analysis
from app.config import settings
from app.database.models import Post as WriterPost, ResearchPost, ResearchReport, TrackedProfile
from app.database.session import SessionLocal
from app.research import collect_from_source, expand_keywords, monitored_handles
from app.research.keyword_search import NICHES
from app.reports import build_report, posts_to_csv, render_html, render_markdown, render_pdf
from app.sources import (
    AccountMonitorSource,
    ContentLibrarySource,
    ManualImportSource,
    ThreadsApiSource,
)

from . import state


def _source_enabled(db, name: str, type_: str) -> tuple[bool, dict]:
    """Respect both .env allow-list and the per-source switch in the DB."""
    from app.database.repository import get_or_create_source

    src = get_or_create_source(db, name, type_)
    enabled = src.enabled and name in settings.research_enabled_sources
    return enabled, src.config_json


async def run_research(kind: str, params: dict) -> dict:
    """Collect from one or more enabled sources. No HTTP caller waits for this."""
    async with _session() as db:
        stats: dict[str, object] = {}
        if kind in {"all", "threads_api"}:
            enabled, config = _source_enabled(db, "threads_api", "api")
            adapter = ThreadsApiSource(config=config, enabled=enabled)
            for mode in params.get("modes") or ["profile", "insights"]:
                stats[f"threads_{mode}"] = await collect_from_source(
                    db, adapter, {**params, "mode": mode}, job_type=f"threads_{mode}"
                )
        if kind in {"all", "search"}:
            enabled, config = _source_enabled(db, "threads_api", "api")
            # Always journal a search attempt. When Advanced Access is absent,
            # the adapter marks it skipped instead of silently doing nothing.
            scope_configured = bool(
                settings.threads_keyword_search_enabled
                or config.get("keyword_search_enabled")
            )
            keywords = params.get("keywords") or NICHES.get(params.get("niche", ""), [])
            localized = expand_keywords(keywords, params.get("languages"))[:5]
            adapter = ThreadsApiSource(config=config, enabled=enabled)
            search_runs = []
            # One clear skipped record is enough when access was never enabled.
            queries = (localized or [""]) if scope_configured else (localized[:1] or [""])
            for keyword in queries:
                search_runs.append(await collect_from_source(
                    db, adapter,
                    {**params, "mode": "search", "query": keyword, "external_only": True},
                    job_type="keyword_search",
                ))
            stats["search"] = {
                "keywords": localized,
                "runs": search_runs,
                "new": sum(int(r.get("new", 0)) for r in search_runs),
                "duplicates": sum(int(r.get("duplicate_count", r.get("duplicates", 0))) for r in search_runs),
            }
        if kind in {"all", "content_library"}:
            enabled, config = _source_enabled(db, "content_library", "research")
            adapter = ContentLibrarySource(config=config, enabled=enabled)
            stats["content_library"] = await collect_from_source(
                db, adapter,
                {**params, "keywords": params.get("keywords") or NICHES.get(params.get("niche", ""), [])[:3]},
                job_type="content_library",
            )
        if kind in {"all", "monitor"}:
            enabled, config = _source_enabled(db, "account_monitor", "monitor")
            adapter = AccountMonitorSource(config=config, enabled=enabled)
            stats["monitor"] = await collect_from_source(
                db, adapter,
                {**params, "handles": monitored_handles(db)},
                job_type="account_monitor",
            )
        if kind == "manual":
            adapter = ManualImportSource()
            stats["manual"] = await collect_from_source(db, adapter, params, job_type="manual_import")
        return stats


class _session:
    """Async context manager wrapping a synchronous SQLAlchemy session."""

    async def __aenter__(self):
        self.db = SessionLocal()
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.db.commit()
            else:
                self.db.rollback()
        finally:
            self.db.close()


async def run_analysis(limit: int = 50) -> dict:
    async with _session() as db:
        posts = db.scalars(
            select(ResearchPost).order_by(ResearchPost.created_at.desc()).limit(limit * 3)
        ).all()
        pending = [p for p in posts if needs_analysis(db, p)][:limit]
        results = await analyze_batch(db, pending, limit=limit)
        return {"analyzed": len(results), "posts": results[:10]}


async def run_report(days: int = 30) -> dict:
    from app.database.repository import count_posts

    async with _session() as db:
        if count_posts(db) == 0:
            return {"status": "skipped", "reason": "no research posts yet"}
        report = await build_report(db, days=days)
        return {"status": "ok", "report_id": report.id, "title": report.title}


async def run_link_check() -> dict:
    """Check accessibility of stored links (HEAD only, safe URLs, no downloads)."""
    import httpx
    from app.database.models import ExternalLink, utcnow
    from app.utils import is_safe_url

    checked = accessible = 0
    async with _session() as db:
        links = db.scalars(select(ExternalLink)).all()
        for link in links:
            if not is_safe_url(link.original_url):
                link.is_accessible = False
                link.checked_at = utcnow()
                continue
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=False) as client:
                    response = await client.head(link.original_url)
                link.is_accessible = response.status_code < 400
                link.checked_at = utcnow()
                checked += 1
                accessible += int(bool(link.is_accessible))
            except httpx.HTTPError:
                link.is_accessible = False
                link.checked_at = utcnow()
    return {"checked": checked, "accessible": accessible}


async def run_auto_publish() -> dict:
    """Atomically publish eligible drafts. Ambiguous failures require manual review."""
    if not settings.auto_publish_enabled:
        return {"status": "disabled"}
    if not settings.threads_access_token:
        return {"status": "skipped", "reason": "THREADS_ACCESS_TOKEN is not configured"}

    from app.publishing_queue import publish_claimed
    from fastapi import HTTPException

    statuses = ["approved"] if settings.auto_publish_require_approval else ["approved", "pending_review", "draft"]
    async with _session() as db:
        posts = db.scalars(
            select(WriterPost).where(WriterPost.status.in_(statuses),
                                     WriterPost.threads_post_id.is_(None))
            .order_by(WriterPost.created_at).limit(settings.auto_publish_batch_size)
        ).all()
        ids = [p.id for p in posts]

    published, errors = [], []
    for post_id in ids:
        try:
            result = await publish_claimed(post_id, allow_unapproved=not settings.auto_publish_require_approval)
            published.append({"post_id": post_id, "threads_post_id": result.threads_post_id,
                              "url": result.url})
        except HTTPException as exc:
            errors.append({"post_id": post_id, "error": exc.detail})
        except Exception as exc:
            errors.append({"post_id": post_id, "error": f"{type(exc).__name__}: {exc}"})
    return {"status": "ok" if not errors else ("partial" if published else "failed"),
            "attempted": len(ids), "published": published, "errors": errors}


# --- task wrappers used by API ------------------------------------------------
# Keep references until completion. This is an in-process queue; long-running
# jobs are returned immediately to the caller, with status via /status.
import asyncio

_RUNNING: set[asyncio.Task] = set()


def _spawn(kind: str, params: dict, factory) -> str:
    task_id = state.new_task(kind, params)

    async def runner():
        try:
            state.set_result(task_id, await factory())
        except Exception as exc:
            state.set_error(task_id, f"{type(exc).__name__}: {exc}")

    task = asyncio.create_task(runner())
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)
    return task_id


async def launch_research(kind: str, params: dict) -> str:
    return _spawn("research", {"kind": kind, **params}, lambda: run_research(kind, params))


async def launch_analysis(limit: int) -> str:
    return _spawn("analysis", {"limit": limit}, lambda: run_analysis(limit))


async def launch_report(days: int) -> str:
    return _spawn("report", {"days": days}, lambda: run_report(days))
