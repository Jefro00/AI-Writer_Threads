"""Growth Studio: batch generation, affiliate offers and transparent post metrics."""
from __future__ import annotations

import csv
import io
import ipaddress
import re
from datetime import datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import (AffiliateOffer, Post, ReferralClick,
                                 WriterCampaign, WriterPostMetrics, utcnow)
from app.database.session import SessionLocal, get_db
from app.marketing.generator import generate_growth_variants
from app.marketing.hooks import GOALS, HOOK_TYPES, PROMO_STYLES
from app.marketing.learning import growth_insights, prompt_feedback
from app.marketing.style_lab import rebuild_patterns, rank_patterns, style_guidance
from app.security import require_admin

router = APIRouter(prefix="/api/growth", tags=["growth"], dependencies=[Depends(require_admin)])


def _check_https(value: str) -> str:
    value = value.strip()
    u = urlsplit(value)
    if u.scheme != "https" or not u.netloc or u.username or u.password or u.fragment:
        raise ValueError("Нужна ссылка HTTPS без логина, пароля или фрагмента")
    host = u.hostname or ""
    if host.lower() == "localhost" or host.lower().endswith(".local"):
        raise ValueError("Нельзя использовать локальный адрес")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host or not re.fullmatch(r"[A-Za-z0-9.-]+", host):
            raise ValueError("Некорректный публичный домен")
    else:
        if not ip.is_global:
            raise ValueError("Нужен публичный адрес")
    return value


class OfferInput(BaseModel):
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z][a-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=120)
    referral_url: str
    description: str = Field(default="", max_length=1500)
    target_audience: str = Field(default="", max_length=500)
    benefits: list[str] = Field(default_factory=list, max_length=10)
    active: bool = True

    @field_validator("referral_url")
    @classmethod
    def url_is_safe(cls, value: str) -> str:
        return _check_https(value)


class GrowthRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    category: str = "Crypto Discussion"
    language: str = "ru"
    goal: str = "clicks"
    hook_type: str = "auto"
    promotion_style: str = "soft"
    offer_slug: str | None = "fomo"
    audience: str = Field(default="Криптоэнтузиасты, в том числе новички", max_length=500)
    variants: int = Field(default=3, ge=1, le=5)
    use_style_lab: bool = True
    writing_style: str = Field(default="mixed", max_length=50)
    style_intensity: int = Field(default=65, ge=0, le=100)

    @field_validator("goal")
    @classmethod
    def valid_goal(cls, v):
        if v not in GOALS: raise ValueError("Unknown goal")
        return v

    @field_validator("hook_type")
    @classmethod
    def valid_hook(cls, v):
        if v not in HOOK_TYPES: raise ValueError("Unknown hook")
        return v

    @field_validator("promotion_style")
    @classmethod
    def valid_promo(cls, v):
        if v not in PROMO_STYLES: raise ValueError("Unknown promotion style")
        return v

    @field_validator("language")
    @classmethod
    def valid_language(cls, v):
        if v not in ("ru", "en"): raise ValueError("Supported: ru, en")
        return v


class MetricsInput(BaseModel):
    views: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    replies: int | None = Field(default=None, ge=0)
    reposts: int | None = Field(default=None, ge=0)
    registrations: int | None = Field(default=None, ge=0)
    revenue: float | None = Field(default=None, ge=0)


def _offer(o: AffiliateOffer) -> dict:
    return {"id": o.id, "slug": o.slug, "name": o.name, "referral_url": o.referral_url,
            "description": o.description, "target_audience": o.target_audience,
            "benefits": o.benefits_json or [], "active": o.active}


@router.get("/offers")
def list_offers(db: Session = Depends(get_db)):
    return [_offer(o) for o in db.scalars(select(AffiliateOffer).order_by(AffiliateOffer.id)).all()]


@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db)):
    rows = db.scalars(select(WriterCampaign).order_by(WriterCampaign.id.desc()).limit(100)).all()
    return [{"id": c.id, "topic": c.topic, "goal": c.goal, "language": c.language,
             "offer_id": c.offer_id, "hook_type": c.hook_type,
             "promotion_style": c.promotion_style,
             "posts": [{"id": p.id, "hook_type": p.hook_type, "status": p.status,
                        "editorial_score": p.editorial_score} for p in
                       db.scalars(select(Post).where(Post.campaign_id == c.id)
                                  .order_by(Post.variant_index)).all()]}
            for c in rows]


@router.post("/offers")
def create_offer(req: OfferInput, db: Session = Depends(get_db)):
    if db.scalar(select(AffiliateOffer).where(AffiliateOffer.slug == req.slug)):
        raise HTTPException(409, "Оффер с таким slug уже существует")
    o = AffiliateOffer(slug=req.slug, name=req.name, referral_url=req.referral_url,
                       description=req.description, target_audience=req.target_audience,
                       benefits_json=req.benefits, active=req.active)
    db.add(o); db.commit(); db.refresh(o)
    return _offer(o)


@router.put("/offers/{slug}")
def update_offer(slug: str, req: OfferInput, db: Session = Depends(get_db)):
    o = db.scalar(select(AffiliateOffer).where(AffiliateOffer.slug == slug))
    if not o: raise HTTPException(404, "Оффер не найден")
    if req.slug != slug: raise HTTPException(422, "slug нельзя изменять")
    for key, val in (("name", req.name), ("referral_url", req.referral_url),
                     ("description", req.description), ("target_audience", req.target_audience),
                     ("benefits_json", req.benefits), ("active", req.active)):
        setattr(o, key, val)
    db.commit(); db.refresh(o)
    return _offer(o)


@router.post("/generate")
async def generate(req: GrowthRequest):
    # Commit the campaign before making a potentially slow AI call. Holding a
    # SQLite write transaction across an HTTP request would lock all writers.
    with SessionLocal() as db:
        offer = db.scalar(select(AffiliateOffer).where(AffiliateOffer.slug == req.offer_slug)) if req.offer_slug else None
        if req.promotion_style != "none" and not offer:
            raise HTTPException(422, "Выбери существующий оффер или отключи промо")
        if offer and not offer.active and req.promotion_style != "none":
            raise HTTPException(422, "Оффер выключен")
        if req.promotion_style == "none":
            offer = None
        offer_id = offer.id if offer else None
        offer_slug = offer.slug if offer else None
        offer_info = _offer(offer) if offer else None
        feedback = prompt_feedback(growth_insights(db))
        selected_patterns = []
        guidance = ""
        if req.use_style_lab:
            # Idempotent: newly collected Research posts immediately enrich Style Lab.
            rebuild_patterns(db, limit=300)
            selected_patterns = rank_patterns(db, topic=req.topic, language=req.language,
                                              style=req.writing_style, limit=5)
            guidance = style_guidance(selected_patterns, intensity=req.style_intensity)
            db.commit()
        campaign = WriterCampaign(topic=req.topic, goal=req.goal, language=req.language,
                                  offer_id=offer_id, hook_type=req.hook_type,
                                  promotion_style=req.promotion_style)
        db.add(campaign); db.commit(); campaign_id = campaign.id

    link = (f"{settings.public_base_url}/go/{offer_slug}?c={campaign_id}&v={{variant_index}}"
            if offer_info and settings.public_base_url else (offer_info["referral_url"] if offer_info else None))
    try:
        output = await generate_growth_variants(
            topic=req.topic, category=req.category, language=req.language,
            goal=req.goal, hook_type=req.hook_type, promotion_style=req.promotion_style,
            offer=offer_info, link=link, audience=req.audience,
            count=req.variants, feedback=feedback, style_guidance=guidance,
        )
        with SessionLocal() as db:
            campaign = db.get(WriterCampaign, campaign_id)
            if not campaign:
                raise HTTPException(409, "Кампания удалена во время генерации")
            campaign.hooks_json = output["hooks"]
            results = []
            for idx, variant in enumerate(output["variants"], start=1):
                text = variant["text"].replace("{variant_index}", str(idx))
                if len(text) > 500:
                    raise HTTPException(502, "Слишком длинный текст после подстановки ссылки")
                post = Post(text=text, category=req.category, language=req.language,
                            status="pending_review", campaign_id=campaign_id,
                            offer_id=offer_id, goal=req.goal,
                            hook_type=variant["hook_type"], variant_index=idx,
                            editorial_score=variant["score"], prompt_version=output["prompt_version"],
                            ai_model=output["ai_model"],
                            tracking_url=(link.replace("{variant_index}", str(idx)) if link else None))
                db.add(post); db.flush()
                results.append({"id": post.id, "text": post.text,
                                "hook_type": post.hook_type, "editorial_score": post.editorial_score,
                                "status": post.status, "language": post.language})
            db.commit()
        return {"campaign_id": campaign_id, "hooks": output["hooks"],
                "posts": results, "tracking_enabled": bool(settings.public_base_url),
                "editorial_score_note": "Эвристическая оценка, не прогноз кликов.",
                "style_sources": [{"id": p["source_post_id"], "author": p["author"], "hook_type": p["hook_type"]} for p in selected_patterns]}
    except Exception:
        # Never leave failed AI generations as misleading empty A/B campaigns.
        with SessionLocal() as db:
            orphan = db.get(WriterCampaign, campaign_id)
            if orphan and not db.scalar(select(Post.id).where(Post.campaign_id == campaign_id)):
                db.delete(orphan)
                db.commit()
        raise


@router.put("/posts/{post_id}/metrics")
def update_metrics(post_id: int, req: MetricsInput, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if not post: raise HTTPException(404, "Пост не найден")
    m = db.get(WriterPostMetrics, post_id)
    if not m:
        m = WriterPostMetrics(post_id=post_id)
        db.add(m)
    for name, value in req.model_dump(exclude_unset=True).items():
        setattr(m, name, value)
    m.updated_at = utcnow()
    db.commit()
    return {"post_id": post_id, **{key: getattr(m, key) for key in MetricsInput.model_fields}, "source": "manual"}


def _summary(db: Session) -> list[dict]:
    clicks = dict(db.execute(select(ReferralClick.post_id, func.count(ReferralClick.id))
                             .where(ReferralClick.post_id.is_not(None))
                             .group_by(ReferralClick.post_id)).all())
    rows = db.execute(select(Post, WriterPostMetrics).outerjoin(WriterPostMetrics,
                      WriterPostMetrics.post_id == Post.id).order_by(Post.created_at.desc()).limit(300)).all()
    out = []
    for post, metric in rows:
        c = clicks.get(post.id, 0)
        views = metric.views if metric else None
        signups = metric.registrations if metric else None
        out.append({"id": post.id, "campaign_id": post.campaign_id, "status": post.status,
                    "hook_type": post.hook_type, "goal": post.goal, "language": post.language,
                    "editorial_score": post.editorial_score, "offer_id": post.offer_id,
                    "views": views, "clicks": c, "registrations": signups,
                    "revenue": metric.revenue if metric else None,
                    "likes": metric.likes if metric else None,
                    "replies": metric.replies if metric else None,
                    "reposts": metric.reposts if metric else None,
                    "ctr_percent": round(c / views * 100, 2) if views else None,
                    "signup_rate_percent": round(signups / c * 100, 2) if c and signups is not None and signups <= c else None,
                    "text_preview": post.text[:130]})
    return out


@router.get("/analytics")
def analytics(db: Session = Depends(get_db)):
    posts = _summary(db)
    data = growth_insights(db)
    offers = {o.id: o.name for o in db.scalars(select(AffiliateOffer)).all()}
    by_offer: dict[int, dict] = {}
    for p in posts:
        if p["offer_id"] is None: continue
        d = by_offer.setdefault(p["offer_id"], {"offer_id": p["offer_id"],
               "name": offers.get(p["offer_id"], "Unknown"), "posts": 0,
               "clicks": 0, "registrations": 0, "revenue": 0.0})
        d["posts"] += 1; d["clicks"] += p["clicks"]
        d["registrations"] += p["registrations"] or 0
        d["revenue"] += p["revenue"] or 0
    mixes = dict(db.execute(select(WriterCampaign.promotion_style, func.count(Post.id))
                            .join(Post, Post.campaign_id == WriterCampaign.id)
                            .where(Post.status == 'published')
                            .group_by(WriterCampaign.promotion_style)).all())
    targets = {"none": 0.70, "soft": 0.20, "direct": 0.10}
    n = sum(mixes.values())
    if n:
        next_type = max(targets, key=lambda style: targets[style] * (n + 1) - mixes.get(style, 0))
    else:
        next_type = 'none'
    return {"totals": {"posts": len(posts), "views": sum(p["views"] or 0 for p in posts),
                       "clicks": sum(p["clicks"] for p in posts),
                       "registrations": sum(p["registrations"] or 0 for p in posts),
                       "revenue": round(sum(p["revenue"] or 0 for p in posts), 2)},
            "posts": posts, "offer_stats": list(by_offer.values()),
            "content_mix": {"published": mixes, "target": {k: int(v * 100) for k, v in targets.items()},
                            "suggested_next": next_type,
                            "note": "70/20/10 — стартовая гипотеза, не универсальная закономерность."},
            "hook_insights": data["hooks"],
            "research_patterns": data["research_patterns"],
            "warnings": [data["warning"], "Просмотры и регистрации вводятся вручную; клики считаются только для редирект-ссылок."]}


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db)):
    rows = _summary(db)
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader(); writer.writerows(rows)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=growth_metrics.csv"})


# Deliberately outside the admin router: this is a public link, not an admin API.
redirect_router = APIRouter(tags=["affiliate"])


@redirect_router.get("/go/{slug}")
def go(slug: str, request: Request, post: int | None = Query(default=None, ge=1),
       c: int | None = Query(default=None, ge=1),
       v: int | None = Query(default=None, ge=1, le=5)):
    with SessionLocal() as db:
        offer = db.scalar(select(AffiliateOffer).where(AffiliateOffer.slug == slug,
                           AffiliateOffer.active.is_(True)))
        if not offer: raise HTTPException(404, "Ссылка недоступна")
        # The destination is an admin-approved HTTPS URL, never passed as input.
        try:
            destination = _check_https(offer.referral_url)
        except ValueError:
            raise HTTPException(503, "Некорректный адрес партнёрского оффера")
        linked_post = None
        if post is not None:
            linked_post = db.get(Post, post)
            if not linked_post or linked_post.offer_id != offer.id:
                raise HTTPException(404, "Пост не привязан к офферу")
        elif c is not None or v is not None:
            if c is None or v is None: raise HTTPException(422, "Нужны c и v")
            linked_post = db.scalar(select(Post).where(Post.campaign_id == c,
                                   Post.variant_index == v, Post.offer_id == offer.id))
            if not linked_post: raise HTTPException(404, "Кампания не найдена")
        # Common social preview crawlers are not user clicks.
        agent = request.headers.get("user-agent", "").lower()
        preview_bots = ("twitterbot", "facebookexternalhit", "telegrambot", "discordbot",
                        "slackbot", "whatsapp", "googlebot", "bingbot", "linkedinbot")
        if not any(bot in agent for bot in preview_bots):
            db.add(ReferralClick(offer_id=offer.id,
                                 post_id=linked_post.id if linked_post else None))
            db.commit()
    return RedirectResponse(destination, status_code=302, headers={"Cache-Control": "no-store"})
