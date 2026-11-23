"""Traffic/funnel metrics and own attribution helpers."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ExternalLink, Funnel, PostMetric, ResearchPost
from app.utils import build_tracked_url


def ctr(clicks: int | None, views: int | None) -> float | None:
    if clicks is None or not views or views <= 0:
        return None
    return round(clicks / views * 100, 4)


def cr(conversions: int | None, clicks: int | None) -> float | None:
    if conversions is None or not clicks or clicks <= 0:
        return None
    return round(conversions / clicks * 100, 4)


def revenue_per_1000_views(revenue: float | None, views: int | None) -> float | None:
    if revenue is None or not views or views <= 0:
        return None
    return round(revenue / views * 1000, 2)


def link_summary(db: Session) -> dict:
    links = db.scalars(select(ExternalLink)).all()
    platforms: dict[str, int] = {}
    for l in links:
        platforms[l.platform_type or "website"] = platforms.get(l.platform_type or "website", 0) + 1
    return {
        "total_links": len(links),
        "unique_domains": len({l.domain for l in links if l.domain}),
        "with_utm": sum(1 for l in links if l.utm_json),
        "with_referral": sum(1 for l in links if l.has_referral),
        "platforms": platforms,
    }


def funnel_summary(db: Session) -> dict:
    funnels = db.scalars(select(Funnel)).all()
    types: dict[str, int] = {}
    proof: dict[str, int] = {}
    for f in funnels:
        types[f.funnel_type or "unknown"] = types.get(f.funnel_type or "unknown", 0) + 1
        proof[f.proof_level] = proof.get(f.proof_level, 0) + 1
    return {
        "total_funnels": len(funnels),
        "by_type": types,
        "by_proof_level": proof,
        "unverified_conversions": sum(1 for f in funnels if f.proof_level in {"L6", "L7"}),
    }


def tracked_link_for_post(post_id: int, campaign: str | None = None, base_url: str = "") -> str:
    return build_tracked_url(base_url, post_id, campaign)
