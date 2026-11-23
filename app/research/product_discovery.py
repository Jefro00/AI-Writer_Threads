"""Product discovery from links and AI-mentioned product names."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ExternalLink, Product, utcnow
from app.utils import parse_url_details


def upsert_product_from_link(db: Session, link: ExternalLink, name: str | None = None) -> Product:
    domain = link.domain or "unknown"
    candidate_name = (name or domain).strip()[:200]
    product = db.scalar(
        select(Product).where(Product.domain == domain, Product.name == candidate_name)
    )
    if product is None:
        product = Product(
            name=candidate_name,
            website=link.normalized_url or link.original_url,
            domain=domain,
            product_category=link.platform_type,
            source_profile_id=link.profile_id,
            first_seen_at=utcnow(),
            last_seen_at=utcnow(),
        )
        db.add(product)
        db.flush()
    else:
        product.last_seen_at = utcnow()
    link.product_id = product.id
    return product


def upsert_product_from_name(db: Session, name: str, profile_id: int | None = None) -> Product | None:
    name = (name or "").strip()
    if not name:
        return None
    product = db.scalar(select(Product).where(Product.name == name))
    if product is None:
        product = Product(name=name[:200], source_profile_id=profile_id, first_seen_at=utcnow(), last_seen_at=utcnow())
        db.add(product)
        db.flush()
    else:
        product.last_seen_at = utcnow()
    return product


def apply_landing_card(db: Session, product: Product, card: dict) -> None:
    """Merge a safe public landing-page analysis into the product card."""
    if not card or card.get("error"):
        return
    product.description = card.get("description") or product.description
    product.target_audience = card.get("target_audience") or product.target_audience
    product.pricing_model = ", ".join(card.get("pricing") or []) or product.pricing_model
    landing = dict(product.landing_analysis_json or {})
    landing.update({
        "main_offer": card.get("main_offer"),
        "ctas": card.get("ctas"),
        "has_free_tier": card.get("has_free_tier"),
        "has_registration": card.get("has_registration"),
        "has_demo": card.get("has_demo"),
        "has_referral_program": card.get("has_referral_program"),
        "community_links": card.get("community_links"),
        "advantages": card.get("advantages"),
    })
    product.landing_analysis_json = landing
