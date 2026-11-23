"""AI analysis orchestration for a single post and for batches.

Key property: re-analysis only happens when the text hash or the prompt version
changed. Results are saved with their source data and confidence.
"""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ExternalLink, ResearchPost, TrackedProfile
from app.database.repository import (
    get_cached_analysis,
    save_analysis,
    upsert_classification,
)
from app.research.funnel_detector import process_funnel_analysis
from app.utils import content_hash, text_hash

from . import classifier, cta_analyzer, funnel_analyzer, language, strategy_analyzer, viral_detector
from .provider import AIError, ai_configured
from .prompts import PROMPT_VERSIONS

AGENTS = ("content_classifier", "strategy_analyzer", "cta_analyzer", "funnel_analyzer", "viral_detector")


def needs_analysis(db: Session, post: ResearchPost) -> bool:
    """True if any agent lacks a cached result for the current prompt version."""
    for agent in AGENTS:
        version = PROMPT_VERSIONS[agent]
        h = content_hash(post.original_text, f"agent:{agent}")
        if get_cached_analysis(db, h, version, agent) is None:
            return True
    return False


async def analyze_post(
    db: Session,
    post: ResearchPost,
    *,
    force: bool = False,
    with_funnel: bool = True,
) -> dict:
    """Run all agents on one post. Returns a stats dict."""
    if not ai_configured():
        return {"post_id": post.id, "status": "skipped", "reason": "AI not configured"}

    author: TrackedProfile | None = None
    if post.author_id:
        author = db.get(TrackedProfile, post.author_id)
    links = db.scalars(
        select(ExternalLink).where(ExternalLink.post_id == post.id)
    ).all()
    link_text = ", ".join(str(l.original_url) for l in links)
    bio = author.bio if author else ""

    # Factories, not coroutine objects: an error on one agent can't leave the
    # other agents' coroutines unawaited.
    tasks: list[tuple[str, Any]] = [
        ("content_classifier", lambda: classifier.classify(post.original_text, bio or "")),
        ("strategy_analyzer", lambda: strategy_analyzer.analyze(post.original_text)),
        ("cta_analyzer", lambda: cta_analyzer.analyze(post.original_text)),
        ("funnel_analyzer", lambda: funnel_analyzer.analyze(post.original_text, bio, link_text)),
        ("viral_detector", lambda: viral_detector.analyze(post.original_text)),
    ]

    results: dict[str, dict] = {}
    errors: list[str] = []
    # Sequential to respect free-tier rate limits; cache means this is cheap.
    for agent, coro in tasks:
        version = PROMPT_VERSIONS[agent]
        h = content_hash(post.original_text, f"agent:{agent}")
        cached = None if force else get_cached_analysis(db, h, version, agent)
        if cached is not None:
            results[agent] = cached.result_json
            continue
        try:
            data = await coro()
        except AIError as exc:
            errors.append(f"{agent}: {exc}")
            continue
        results[agent] = data
        source_data = {
            "original_text": post.original_text,
            "author": author.username if author else None,
            "links": link_text,
            "text_hash": text_hash(post.original_text),
        }
        save_analysis(
            db,
            agent_name=agent,
            input_hash=h,
            prompt_version=version,
            result=data,
            source_data=source_data,
            summary=str(data.get("summary") or data.get("pattern") or "")[:500],
            confidence=float(data.get("confidence") or 0.0),
            post_id=post.id,
            profile_id=post.author_id,
        )
        # Release the SQLite writer lock before the next slow network call.
        db.commit()

    # Persist consolidated classification record (multi-label).
    cls = results.get("content_classifier", {})
    strategy = results.get("strategy_analyzer", {})
    cta = results.get("cta_analyzer", {})
    mechanics = strategy.get("mechanics") or []
    if isinstance(mechanics, list):
        mechanics = [m.get("name") for m in mechanics if isinstance(m, dict) and m.get("name")]
    upsert_classification(
        db,
        post.id,
        "combined",
        PROMPT_VERSIONS["content_classifier"],
        {
            "niche": cls.get("niche"),
            "subcategories": cls.get("subcategories") or [],
            "language": language.resolve_language(cls.get("language"), post.original_text),
            "format": cls.get("format"),
            "tone": cls.get("tone"),
            "intent": cls.get("intent"),
            "target_audience": cls.get("target_audience") or [],
            "marketing_mechanics": mechanics,
            "ctas": cta.get("ctas") or [],
            "confidence": cls.get("confidence") or 0.0,
        },
    )
    post.language = language.resolve_language(cls.get("language"), post.original_text)

    funnels_created = 0
    if with_funnel and "funnel_analyzer" in results:
        funnels_created = len(process_funnel_analysis(db, post, results["funnel_analyzer"]))
    db.flush()
    db.commit()

    return {
        "post_id": post.id,
        "status": "ok" if not errors else ("partial" if results else "failed"),
        "agents": sorted(results.keys()),
        "funnels_created": funnels_created,
        "errors": errors,
    }


async def analyze_batch(db: Session, posts: list[ResearchPost], *, limit: int | None = None) -> list[dict]:
    out = []
    for post in posts[:limit] if limit else posts:
        if not needs_analysis(db, post):
            out.append({"post_id": post.id, "status": "cached"})
            continue
        out.append(await analyze_post(db, post))
        # Yield to the event loop so the API stays responsive.
        await asyncio.sleep(0)
    return out


async def analyze_profile_agent(db: Session, profile: TrackedProfile, data: dict) -> dict:
    from .competitor_analyzer import analyze_profile
    from .prompts import PROMPT_VERSIONS

    h = content_hash(str(data), f"profile:{profile.id}")
    cached = get_cached_analysis(db, h, PROMPT_VERSIONS["competitor_analyzer"], "competitor_analyzer")
    if cached:
        return cached.result_json
    result = await analyze_profile(data)
    save_analysis(
        db,
        agent_name="competitor_analyzer",
        input_hash=h,
        prompt_version=PROMPT_VERSIONS["competitor_analyzer"],
        result=result,
        source_data=data,
        confidence=float(result.get("confidence") or 0.0),
        profile_id=profile.id,
    )
    return result
