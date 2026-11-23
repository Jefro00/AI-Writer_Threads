"""Post performance metrics. All formulas follow the technical specification."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import PostMetric, ResearchPost


def engagement_rate(views: int | None, likes: int | None, replies: int | None, reposts: int | None, quotes: int | None) -> float | None:
    if not views or views <= 0:
        return None
    parts = [p for p in (likes, replies, reposts, quotes) if p is not None]
    return round(sum(parts) / views * 100, 4)


def reply_rate(views: int | None, replies: int | None) -> float | None:
    if not views or views <= 0 or replies is None:
        return None
    return round(replies / views * 100, 4)


def share_rate(views: int | None, reposts: int | None, quotes: int | None) -> float | None:
    if not views or views <= 0:
        return None
    parts = [p for p in (reposts, quotes) if p is not None]
    return round(sum(parts) / views * 100, 4)


def growth_velocity(metrics: list[PostMetric]) -> float | None:
    """Average view growth per day across the observation history."""
    points = [m for m in metrics if m.views is not None and m.collected_at]
    if len(points) < 2:
        return None
    points.sort(key=lambda m: m.collected_at)
    first, last = points[0], points[-1]
    days = (last.collected_at - first.collected_at).total_seconds() / 86400
    if days <= 0:
        return None
    return round((last.views - first.views) / days, 2)  # type: ignore[operator]


def metrics_series(db: Session, post_id: int) -> list[dict]:
    rows = db.scalars(
        select(PostMetric).where(PostMetric.post_id == post_id).order_by(PostMetric.collected_at)
    ).all()
    return [
        {
            "collected_at": m.collected_at.isoformat() if m.collected_at else None,
            "views": m.views, "likes": m.likes, "replies": m.replies,
            "reposts": m.reposts, "quotes": m.quotes,
            "engagement_rate": m.engagement_rate, "data_source": m.data_source,
            "is_estimated": m.is_estimated,
        }
        for m in rows
    ]


def post_performance(db: Session, post: ResearchPost) -> dict:
    rows = db.scalars(
        select(PostMetric).where(PostMetric.post_id == post.id).order_by(PostMetric.collected_at)
    ).all()
    last = rows[-1] if rows else None
    views = last.views if last else None
    likes = last.likes if last else None
    replies = last.replies if last else None
    reposts = last.reposts if last else None
    quotes = last.quotes if last else None
    return {
        "views": views, "likes": likes, "replies": replies,
        "reposts": reposts, "quotes": quotes,
        "engagement_rate": engagement_rate(views, likes, replies, reposts, quotes),
        "reply_rate": reply_rate(views, replies),
        "share_rate": share_rate(views, reposts, quotes),
        "growth_velocity": growth_velocity(rows),
        "observations": len(rows),
    }
