"""Author-level performance, medians first (resistant to viral outliers)."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from statistics import mean, median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    PostClassification,
    PostMetric,
    ProfileObservation,
    ResearchPost,
    TrackedProfile,
    utcnow,
)
from .outlier_detection import detect_outliers


def author_stats(db: Session, profile: TrackedProfile) -> dict:
    posts = db.scalars(
        select(ResearchPost).where(ResearchPost.author_id == profile.id)
    ).all()
    post_ids = [p.id for p in posts]
    metrics = db.scalars(
        select(PostMetric).where(PostMetric.post_id.in_(post_ids)).order_by(PostMetric.collected_at)
    ).all() if post_ids else []

    latest_by_post: dict[int, PostMetric] = {}
    for m in metrics:
        latest_by_post[m.post_id] = m

    views = [m.views for m in latest_by_post.values() if m.views is not None]
    ers = [m.engagement_rate for m in latest_by_post.values() if m.engagement_rate is not None]
    med_views = median(views) if views else None

    post_rows = []
    for p in posts:
        m = latest_by_post.get(p.id)
        post_rows.append({
            "id": p.id,
            "views": m.views if m else None,
            "engagement_rate": m.engagement_rate if m else None,
        })
    detect_outliers(post_rows)

    # Topic distribution & CTA share from classifications.
    classifications = db.scalars(
        select(PostClassification).where(
            PostClassification.post_id.in_(post_ids),
            PostClassification.agent_name == "combined",
        )
    ).all() if post_ids else []
    topics: Counter = Counter()
    cta_posts = 0
    commercial_posts = 0
    for c in classifications:
        for sub in c.subcategories_json or []:
            topics[str(sub)] += 1
        if c.ctas_json:
            cta_posts += 1
        if any("sell" in str(m).lower() or "launch" in str(m).lower() for m in c.marketing_mechanics_json or []):
            commercial_posts += 1

    # Posting regularity: posts per active week over the observation window.
    dates = sorted(p.published_at for p in posts if p.published_at)
    regularity = None
    if len(dates) >= 2:
        span_days = (dates[-1] - dates[0]).days or 1
        regularity = round(len(dates) / (span_days / 7), 2)

    # Follower dynamics.
    observations = db.scalars(
        select(ProfileObservation)
        .where(ProfileObservation.profile_id == profile.id)
        .order_by(ProfileObservation.observed_at)
    ).all()
    follower_dynamics = [
        {"at": o.observed_at.isoformat() if o.observed_at else None, "followers": o.followers_count}
        for o in observations
    ]

    return {
        "profile_id": profile.id,
        "username": profile.username,
        "followers": profile.followers_count,
        "segment": profile.segment,
        "posts_count": len(posts),
        "median_views": med_views,
        "avg_views": round(mean(views), 2) if views else None,
        "median_er": round(median(ers), 4) if ers else None,
        "successful_posts": sum(1 for p in post_rows if p.get("is_outlier")),
        "regularity_posts_per_week": regularity,
        "topics": dict(topics.most_common(10)),
        "commercial_posts": commercial_posts,
        "cta_share": round(cta_posts / len(posts) * 100, 1) if posts else None,
        "follower_dynamics": follower_dynamics,
    }


def author_leaderboard(db: Session, metric: str = "median_views", limit: int = 20) -> list[dict]:
    profiles = db.scalars(select(TrackedProfile)).all()
    rows = [author_stats(db, p) for p in profiles]
    key_map = {
        "median_views": "median_views",
        "regularity": "regularity_posts_per_week",
        "engagement": "median_er",
        "commercial": "commercial_posts",
        "diversity": "topics",
        "funnels": "commercial_posts",
    }
    key = key_map.get(metric, "median_views")
    rows.sort(key=lambda r: (r.get(key) is not None, r.get(key) if isinstance(r.get(key), (int, float)) else 0), reverse=True)
    return rows[:limit]
