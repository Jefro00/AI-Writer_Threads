"""Time-series helpers for dashboard dynamics."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ResearchPost


def posts_per_day(db: Session, days: int = 30) -> list[dict]:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    rows = db.scalars(
        select(ResearchPost).where(ResearchPost.published_at >= since)
    ).all()
    buckets: dict[str, int] = defaultdict(int)
    for r in rows:
        if r.published_at:
            buckets[r.published_at.date().isoformat()] += 1
    return [{"date": day, "posts": count} for day, count in sorted(buckets.items())]


def distribution(db: Session, field: str) -> list[dict]:
    """Simple DB-side count distribution on a ResearchPost column."""
    from app.database.models import PostClassification

    counter: dict[str, int] = defaultdict(int)
    if field == "language":
        # Every post has a detected language, even before AI analysis.
        for lang in db.scalars(select(ResearchPost.language)).all():
            counter[lang or "und"] += 1
    elif field in {"niche", "format"}:
        rows = db.scalars(
            select(PostClassification).where(
                PostClassification.agent_name.in_(["combined", "manual"])
            )
        ).all()
        ai_by_post = {r.post_id: r for r in rows if r.agent_name == "combined"}
        manual_by_post = {r.post_id: r for r in rows if r.agent_name == "manual"}
        for pid in set(ai_by_post) | set(manual_by_post):
            row = ai_by_post.get(pid) or manual_by_post.get(pid)
            key = (row.niche if field == "niche" else row.format) or "unknown"
            counter[key] += 1
    else:
        column = getattr(ResearchPost, field, None)
        if column is None:
            return []
        for value in db.scalars(select(column)).all():
            counter[str(value)] += 1
    return [{"key": k, "count": v} for k, v in sorted(counter.items(), key=lambda x: -x[1])]
