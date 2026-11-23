"""Evidence-aware feedback from own published posts and analyzed research posts."""
from __future__ import annotations

from collections import Counter
from sqlalchemy import select, func

from app.database.models import (Post, ReferralClick, WriterPostMetrics,
                                 PostClassification, ResearchPost)


def growth_insights(db) -> dict:
    posts = db.execute(
        select(Post.hook_type, WriterPostMetrics.views, func.count(ReferralClick.id))
        .join(WriterPostMetrics, WriterPostMetrics.post_id == Post.id)
        .outerjoin(ReferralClick, ReferralClick.post_id == Post.id)
        .where(Post.status == "published", Post.hook_type.is_not(None))
        .group_by(Post.id, Post.hook_type, WriterPostMetrics.views)
    ).all()
    groups: dict[str, dict] = {}
    for hook, views, clicks in posts:
        d = groups.setdefault(hook, {"hook_type": hook, "posts": 0, "views": 0, "clicks": 0})
        d["posts"] += 1
        d["views"] += views or 0
        d["clicks"] += clicks or 0
    for d in groups.values():
        d["ctr_percent"] = round(d["clicks"] / d["views"] * 100, 2) if d["views"] else None
    # Research patterns: tag counts only, never reproduce original content.
    classifications = db.execute(select(PostClassification.marketing_mechanics_json).limit(100)).all()
    patterns = Counter()
    for (items,) in classifications:
        if isinstance(items, list):
            patterns.update(x for x in items if isinstance(x, str) and x)
    return {
        "hooks": sorted(groups.values(), key=lambda x: (x["views"] >= 100, x["ctr_percent"] or 0), reverse=True),
        "research_patterns": [name for name, _ in patterns.most_common(5)],
        "sample_posts": len(posts),
        "warning": "Исторические корреляции, не доказательство причинности и не прогноз CTR.",
    }


def prompt_feedback(insights: dict) -> str:
    parts = []
    trustworthy = [h for h in insights["hooks"] if h["posts"] >= 2 and h["views"] >= 100]
    if trustworthy:
        parts.append("Own historical results (observational; NOT proof of causation): " +
                     "; ".join(f"{h['hook_type']}: {h['ctr_percent']}% raw CTR, n={h['posts']}" for h in trustworthy[:3]))
    if insights["research_patterns"]:
        parts.append("Commonly tagged mechanics in imported Research data (inspiration only): " +
                     ", ".join(insights["research_patterns"][:5]))
    return "\n".join(parts)
