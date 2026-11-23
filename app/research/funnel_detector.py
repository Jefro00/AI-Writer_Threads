"""Turn AI funnel analysis + observed links into persisted funnels and proof levels."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    ExternalLink,
    Funnel,
    FunnelStep,
    ResearchPost,
    utcnow,
)
from app.utils import clamp

from .product_discovery import upsert_product_from_link, upsert_product_from_name

PROOF_ORDER = ["L1", "L2", "L3", "L4", "L5", "L6", "L7"]


def max_proof(levels: list[str] | None) -> str:
    if not levels:
        return "L1"
    valid = [p for p in levels if p in PROOF_ORDER]
    if not valid:
        return "L1"
    return max(valid, key=PROOF_ORDER.index)


def process_funnel_analysis(db: Session, post: ResearchPost, analysis: dict) -> list[Funnel]:
    """Create a funnel for a post from the Funnel Detective output.

    Only public observations (L1-L5) are stored as observed. L6/L7 are only
    stored if the AI explicitly marks is_observed=true AND provides evidence —
    which in practice never happens for other people's accounts.
    """
    if not analysis or analysis.get("error"):
        return []
    funnel_type = analysis.get("funnel_type") or "Unknown"
    stages = analysis.get("stages") or []
    if not isinstance(stages, list):
        stages = []

    product = None
    links = db.scalars(select(ExternalLink).where(ExternalLink.post_id == post.id)).all()
    for link in links:
        product = upsert_product_from_link(db, link)
        break
    mentions = analysis.get("product_mentions") or []
    if product is None and mentions:
        product = upsert_product_from_name(db, str(mentions[0]), post.author_id)

    levels = [str(s.get("proof_level", "L1")) for s in stages if isinstance(s, dict)]
    proof = max_proof(levels)
    # Never promote beyond L5 from public material unless hard evidence exists.
    evidence = analysis.get("evidence") or []
    if proof in {"L6", "L7"} and not evidence:
        proof = "L5"

    funnel = Funnel(
        product_id=product.id if product else None,
        source_profile_id=post.author_id,
        entry_post_id=post.id,
        funnel_type=funnel_type if funnel_type != "Unknown" else "Direct Website",
        destination_url=links[0].normalized_url if links else None,
        destination_platform=links[0].platform_type if links else None,
        funnel_description=analysis.get("summary") or build_description(stages),
        confidence_score=clamp(analysis.get("confidence")),
        verified_status="observed" if proof in {"L1", "L2", "L3", "L4", "L5"} else "unverified",
        proof_level=proof,
        steps_json=stages,
        evidence_json=evidence,
        created_at=utcnow(),
    )
    db.add(funnel)
    db.flush()

    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            continue
        step_proof = str(stage.get("proof_level", "L1"))
        db.add(FunnelStep(
            funnel_id=funnel.id,
            step_order=int(stage.get("order", index)),
            step_type=str(stage.get("step_type", "step"))[:60],
            description=stage.get("description"),
            evidence_url=stage.get("evidence_url"),
            confidence=clamp(stage.get("confidence")),
            is_observed=bool(stage.get("is_observed", True)) and step_proof not in {"L6", "L7"},
            proof_level=step_proof if step_proof in PROOF_ORDER else "L1",
        ))
    return [funnel]


def build_description(stages: list[dict]) -> str:
    names = [str(s.get("step_type")) for s in stages if isinstance(s, dict) and s.get("step_type")]
    return " → ".join(names) if names else "Наблюдаемая воронка из публичных данных"
