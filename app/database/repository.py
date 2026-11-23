"""Small reusable data-access helpers used by collectors, AI and API layers.

These helpers deliberately avoid business decisions (no AI calls, no network).
They only translate operations into SQLAlchemy statements.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .models import (
    AiAnalysis,
    CollectionJob,
    PostClassification,
    PostMetric,
    ResearchPost,
    ResearchSource,
    TrackedProfile,
    utcnow,
)


def get_or_create_source(db: Session, name: str, type_: str, config: dict | None = None) -> ResearchSource:
    src = db.scalar(select(ResearchSource).where(ResearchSource.name == name))
    if src:
        return src
    src = ResearchSource(name=name, type=type_, config_json=config or {}, enabled=True)
    db.add(src)
    db.flush()
    return src


def start_job(db: Session, source_id: int | None, job_type: str, params: dict | None = None) -> CollectionJob:
    job = CollectionJob(
        source_id=source_id,
        job_type=job_type,
        status="running",
        params_json=params or {},
        started_at=utcnow(),
    )
    db.add(job)
    db.flush()
    return job


def finish_job(
    db: Session,
    job: CollectionJob,
    *,
    status: str = "success",
    found: int = 0,
    new: int = 0,
    duplicates: int = 0,
    errors: int = 0,
    error_message: str | None = None,
    error_log: list | None = None,
) -> CollectionJob:
    job.status = status
    job.found_count = found
    job.new_count = new
    job.duplicate_count = duplicates
    job.error_count = errors
    job.error_message = error_message
    job.error_log_json = error_log or []
    job.finished_at = utcnow()
    if job.source_id:
        src = db.get(ResearchSource, job.source_id)
        if src:
            src.last_run_at = job.finished_at
    db.flush()
    return job


def get_or_create_profile(
    db: Session,
    username: str,
    *,
    source_id: int | None = None,
    profile_url: str | None = None,
    bio: str | None = None,
    followers_count: int | None = None,
    niches: list | None = None,
    language: str | None = None,
) -> tuple[TrackedProfile, bool]:
    username = (username or "").strip().lstrip("@")
    row = db.scalar(select(TrackedProfile).where(TrackedProfile.username == username))
    created = row is None
    if row is None:
        row = TrackedProfile(username=username)
        db.add(row)
        db.flush()
    changed = False
    for key, value in {
        "source_id": source_id,
        "profile_url": profile_url,
        "bio": bio,
        "followers_count": followers_count,
        "language": language,
    }.items():
        if value is not None and getattr(row, key) != value:
            setattr(row, key, value)
            changed = True
    if niches:
        row.niches_json = niches
        changed = True
    if changed and not created:
        row.updated_at = utcnow()
    return row, created


def find_post_by_external_id(db: Session, source_id: int, external_id: str) -> ResearchPost | None:
    return db.scalar(
        select(ResearchPost).where(
            ResearchPost.source_id == source_id,
            ResearchPost.external_post_id == external_id,
        )
    )


def add_metric(
    db: Session,
    post_id: int,
    *,
    views: int | None,
    likes: int | None = None,
    replies: int | None = None,
    reposts: int | None = None,
    quotes: int | None = None,
    engagement_rate: float | None = None,
    data_source: str | None = None,
    is_estimated: bool = False,
    collected_at: datetime | None = None,
) -> PostMetric:
    if engagement_rate is None:
        known_views = views if views and views > 0 else None
        interactions = sum(v for v in (likes, replies, reposts, quotes) if v is not None)
        engagement_rate = round(interactions / known_views * 100, 4) if known_views is not None else None
    metric = PostMetric(
        post_id=post_id,
        views=views,
        likes=likes,
        replies=replies,
        reposts=reposts,
        quotes=quotes,
        engagement_rate=engagement_rate,
        data_source=data_source,
        is_estimated=is_estimated,
        collected_at=collected_at or utcnow(),
    )
    db.add(metric)
    db.flush()
    return metric


def upsert_classification(
    db: Session,
    post_id: int,
    agent_name: str,
    prompt_version: str,
    payload: dict,
) -> PostClassification:
    row = db.scalar(
        select(PostClassification).where(
            PostClassification.post_id == post_id,
            PostClassification.agent_name == agent_name,
            PostClassification.prompt_version == prompt_version,
        )
    )
    if row is None:
        row = PostClassification(
            post_id=post_id, agent_name=agent_name, prompt_version=prompt_version
        )
        db.add(row)
    mapping = {
        "niche": "niche",
        "subcategories": "subcategories_json",
        "language": "language",
        "format": "format",
        "tone": "tone",
        "intent": "intent",
        "target_audience": "target_audience_json",
        "marketing_mechanics": "marketing_mechanics_json",
        "ctas": "ctas_json",
        "confidence": "confidence",
    }
    for src, dst in mapping.items():
        if src in payload:
            setattr(row, dst, payload[src])
    row.result_json = payload
    db.flush()
    return row


def get_cached_analysis(
    db: Session, input_hash: str, prompt_version: str, agent_name: str
) -> AiAnalysis | None:
    return db.scalar(
        select(AiAnalysis).where(
            AiAnalysis.input_hash == input_hash,
            AiAnalysis.prompt_version == prompt_version,
            AiAnalysis.agent_name == agent_name,
        )
    )


def save_analysis(
    db: Session,
    *,
    agent_name: str,
    input_hash: str,
    prompt_version: str,
    result: dict,
    source_data: dict | None = None,
    summary: str | None = None,
    confidence: float = 0.0,
    post_id: int | None = None,
    profile_id: int | None = None,
) -> AiAnalysis:
    row = get_cached_analysis(db, input_hash, prompt_version, agent_name)
    if row is None:
        row = AiAnalysis(
            agent_name=agent_name,
            input_hash=input_hash,
            prompt_version=prompt_version,
        )
        db.add(row)
    row.result_json = result
    row.source_data_json = source_data or {}
    row.summary = summary
    row.confidence = confidence
    row.post_id = post_id
    row.profile_id = profile_id
    row.created_at = utcnow()
    db.flush()
    return row


def latest_metric(db: Session, post_id: int) -> PostMetric | None:
    return db.scalar(
        select(PostMetric)
        .where(PostMetric.post_id == post_id)
        .order_by(PostMetric.collected_at.desc())
    )


def count_posts(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(ResearchPost)) or 0)
