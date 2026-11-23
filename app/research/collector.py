"""Collection orchestrator: source -> normalize -> dedupe -> persist -> journal."""
from __future__ import annotations

from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Comment, ExternalLink, ProfileObservation, ResearchPost, utcnow
from app.database.repository import (
    add_metric,
    finish_job,
    get_or_create_source,
    start_job,
)
from app.sources.base import RawPost, SourceResult
from app.utils import extract_urls, is_safe_url, parse_url_details

from .deduplicator import deduplicate
from .normalizer import normalize_post, normalize_profile


async def collect_from_source(
    db: Session,
    adapter,
    params: dict,
    *,
    source_name: str | None = None,
    job_type: str | None = None,
) -> dict:
    """Run one adapter and persist everything it returns. Returns job stats."""
    name = source_name or adapter.name
    source = get_or_create_source(db, name, adapter.source_type)
    if not adapter.is_enabled():
        job = start_job(db, source.id, job_type or "disabled", params)
        finish_job(
            db, job, status="skipped",
            error_message=f"Source '{name}' is disabled or not configured",
        )
        return _stats(job)

    job = start_job(db, source.id, job_type or adapter.name, params)
    result: SourceResult | None = None
    try:
        result = await adapter.collect(params)
    except Exception as exc:  # adapters should not raise, but be defensive
        finish_job(db, job, status="failed", error_message=f"{type(exc).__name__}: {exc}")
        return _stats(job)

    if result.skipped:
        finish_job(db, job, status="skipped", error_message=result.skipped)
        return _stats(job)

    if result.insights:
        _persist_insights(db, result.insights, source.id)

    found = result.found
    new_count = duplicate_count = 0
    for raw_profile in result.profiles:
        try:
            normalize_profile(db, raw_profile, name, adapter.source_type)
            _persist_profile_observation(db, raw_profile)
        except Exception as exc:
            result.errors.append(f"Profile error: {exc}")

    for raw in result.posts:
        if not (raw.text or "").strip():
            continue  # media-only posts have nothing to research
        try:
            post, is_new, reason = persist_raw_post(db, raw, source, name, adapter.source_type)
            if is_new:
                new_count += 1
            else:
                duplicate_count += 1
        except Exception as exc:
            result.errors.append(f"Post error: {exc}")

    error_count = len(result.errors)
    status = "success"
    if error_count and new_count == 0:
        status = "failed"
    elif error_count:
        status = "partial"
    finish_job(
        db, job,
        status=status,
        found=found,
        new=new_count,
        duplicates=duplicate_count,
        errors=error_count,
        error_message=result.errors[0] if result.errors else None,
        error_log=result.errors,
    )
    return _stats(job)


def persist_raw_post(
    db: Session,
    raw: RawPost,
    source,
    name: str,
    source_type: str,
) -> tuple[ResearchPost, bool, str]:
    """Insert a post + first metric snapshot. Returns (post, is_new, reason)."""
    post = normalize_post(db, raw, source_name=name, source_type=source_type, source_id=source.id)
    is_duplicate, reason = deduplicate(db, post)
    if is_duplicate:
        # Update the existing row's metric history instead of creating a dup.
        existing = _find_existing(db, post, reason)
        if existing and any(v is not None for v in (raw.views, raw.likes, raw.replies, raw.reposts, raw.quotes)):
            add_metric(
                db, existing.id,
                views=raw.views, likes=raw.likes, replies=raw.replies,
                reposts=raw.reposts, quotes=raw.quotes,
                data_source=name,
            )
            existing.updated_at = utcnow()
        return existing, False, reason

    db.add(post)
    db.flush()
    if any(v is not None for v in (raw.views, raw.likes, raw.replies, raw.reposts, raw.quotes)):
        add_metric(
            db, post.id,
            views=raw.views, likes=raw.likes, replies=raw.replies,
            reposts=raw.reposts, quotes=raw.quotes,
            data_source=name,
        )
    _persist_comments(db, post, raw.comments)
    _persist_links(db, post, raw, name)
    _persist_manual_extras(db, post, raw)
    return post, True, "new"


def _persist_manual_extras(db: Session, post: ResearchPost, raw: RawPost) -> None:
    """Persist product / mechanic supplied in a manual entry."""
    from app.database.models import ExternalLink, PostClassification, Product
    from app.research.product_discovery import upsert_product_from_name

    data = raw.raw or {}
    product_name = data.get("product")
    niche = data.get("niche")
    mechanic = data.get("mechanic")
    if product_name and isinstance(product_name, str):
        product = upsert_product_from_name(db, product_name, post.author_id)
        for link in db.scalars(select(ExternalLink).where(ExternalLink.post_id == post.id)).all():
            link.product_id = product.id
    if niche or mechanic:
        from app.ai.prompts import PROMPT_VERSIONS

        db.add(PostClassification(
            post_id=post.id,
            agent_name="manual",
            prompt_version=PROMPT_VERSIONS["content_classifier"],
            niche=niche if isinstance(niche, str) else None,
            marketing_mechanics_json=[mechanic] if isinstance(mechanic, str) and mechanic else [],
            result_json={"product": product_name, "niche": niche, "mechanic": mechanic},
            confidence=1.0,
        ))


def _find_existing(db: Session, post: ResearchPost, reason: str) -> ResearchPost | None:
    from app.database.repository import find_post_by_external_id

    if reason == "same_source_external_id" and post.external_post_id:
        return find_post_by_external_id(db, post.source_id, post.external_post_id)
    if reason == "same_url" and post.post_url:
        return db.scalar(select(ResearchPost).where(ResearchPost.post_url == post.post_url))
    if reason == "same_text_hash" and post.text_hash:
        return db.scalar(select(ResearchPost).where(ResearchPost.text_hash == post.text_hash).limit(1))
    return None


def _persist_comments(db: Session, post: ResearchPost, comments: list[dict]) -> None:
    for c in comments:
        if not isinstance(c, dict):
            continue
        text = str(c.get("text") or c.get("message") or "").strip()
        if not text:
            continue
        db.add(Comment(
            post_id=post.id,
            external_id=str(c.get("id")) if c.get("id") else None,
            author_username=c.get("username") or c.get("author"),
            text=text,
            language=c.get("language"),
            likes=c.get("likes"),
            is_reply=bool(c.get("is_reply", False)),
            collected_at=utcnow(),
        ))


def _persist_links(db: Session, post: ResearchPost, raw: RawPost, source_name: str) -> None:
    urls = extract_urls(post.original_text)
    for url in urls:
        details = parse_url_details(url)
        db.add(ExternalLink(
            post_id=post.id,
            profile_id=post.author_id,
            original_url=url,
            normalized_url=details["normalized_url"],
            domain=details["domain"],
            platform_type=details["platform_type"],
            utm_json=details["utm"],
            has_referral=details["has_referral"],
            detected_at=utcnow(),
        ))


def _persist_profile_observation(db: Session, raw_profile) -> None:
    from app.database.models import TrackedProfile

    profile = db.scalar(select(TrackedProfile).where(TrackedProfile.username == raw_profile.username.lstrip("@")))
    if not profile:
        return
    db.add(ProfileObservation(
        profile_id=profile.id,
        followers_count=raw_profile.followers_count,
        bio=raw_profile.bio,
        metrics_json={"language": raw_profile.language, "niches": raw_profile.niches},
        observed_at=utcnow(),
    ))


def _persist_insights(db: Session, data: dict, source_id: int) -> None:
    """Persist own-account Insights as metric snapshots on matching research posts.

    We only attach metrics to posts whose external id we already track (our own
    published posts mirrored into research). Unknown ids are ignored rather than
    inventing records.
    """
    for item in data.get("data", []):
        post_id = item.get("id")
        if not post_id:
            continue
        post = db.scalar(
            select(ResearchPost).where(ResearchPost.external_post_id == str(post_id))
        )
        if not post:
            continue
        values: dict = {}
        for entry in item.get("values", []):
            name = entry.get("name")
            value = entry.get("value")
            if isinstance(value, dict):
                value = value.get("value")
            values[name] = value
        add_metric(
            db, post.id,
            views=values.get("threads_views"),
            likes=values.get("threads_likes"),
            replies=values.get("threads_replies"),
            reposts=values.get("threads_reposts"),
            quotes=values.get("threads_quotes"),
            data_source="threads_insights",
        )


def _stats(job) -> dict:
    return {
        "job_id": job.id,
        "status": job.status,
        "found": job.found_count,
        "new": job.new_count,
        "duplicates": job.duplicate_count,
        "errors": job.error_count,
        "error_message": job.error_message,
    }
