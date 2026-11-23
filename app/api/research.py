"""Research API routes. All admin-protected, paginated and filterable."""
from __future__ import annotations

import base64
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics import (
    author_leaderboard,
    distribution,
    funnel_summary,
    link_summary,
    post_performance,
    posts_per_day,
)
from app.config import settings
from app.database.models import (
    AiAnalysis,
    CollectionJob,
    Experiment,
    ExternalLink,
    Funnel,
    FunnelStep,
    Insight,
    Comment as CommentModel,
    PostClassification as PostClassificationModel,
    PostMetric as PostMetricModel,
    Post as WriterPost,
    PostClassification,
    Product,
    ProfileObservation,
    ResearchPost,
    ResearchReport,
    ResearchSource,
    TrackedProfile,
    WriterBrief,
    utcnow,
)
from app.database.repository import (
    add_metric, count_posts, get_or_create_profile, get_or_create_source,
)
from app.database.session import get_db
from app.reports import build_report, posts_to_csv, render_pdf
from app.research import collect_from_source, expand_keywords
from app.scheduler import launch_analysis, launch_report, launch_research, scheduler_status, state
from app.sources import ManualImportSource
from app.utils import build_tracked_url, segment_for_followers
from app.security import require_admin

from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/research", tags=["research"])
ADMIN = [Depends(require_admin)]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class StartRequest(BaseModel):
    kind: str = "all"  # all|threads_api|search|content_library|monitor|manual
    keywords: list[str] = []
    niche: str | None = None
    languages: list[str] = []
    limit: int = Field(default=25, ge=1, le=200)
    modes: list[str] = []
    query: str | None = None

    @property
    def as_params(self) -> dict:
        return self.model_dump(exclude={"kind"})


class ProfileImportRequest(BaseModel):
    items: list[dict] = []


class SourceUpdateRequest(BaseModel):
    enabled: bool | None = None
    config_json: dict | None = None


class AnalyzeRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)
    post_id: int | None = None
    force: bool = False


class ProfileRequest(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    profile_url: str | None = None
    bio: str | None = None
    followers_count: int | None = None
    language: str | None = None
    niches: list[str] = []
    external_profile_id: str | None = None


class ManualPostRequest(BaseModel):
    text: str = Field(min_length=1)
    post_url: str | None = None
    author: str | None = None
    author_url: str | None = None
    author_bio: str | None = None
    followers: int | None = None
    language: str | None = None
    niche: str | None = None
    published_at: str | None = None
    views: int | None = None
    likes: int | None = None
    replies: int | None = None
    reposts: int | None = None
    quotes: int | None = None
    product: str | None = None
    mechanic: str | None = None


class ImportRequest(BaseModel):
    items: list[dict] = []
    filename: str | None = None
    content_base64: str | None = None


class ReportRequest(BaseModel):
    title: str = "Threads Research Report"
    days: int = Field(default=30, ge=1, le=365)
    report_type: str = "weekly"


class InsightRequest(BaseModel):
    title: str
    description: str
    niche: str | None = None
    sample_size: int = 0
    confidence: float = 0.0
    example_post_ids: list[int] = []
    limitations: str | None = None
    evidence: list[dict] = []


class ExperimentRequest(BaseModel):
    name: str
    hypothesis: str
    niche: str | None = None
    format: str | None = None
    cta: str | None = None
    planned_posts: int = 10


class BriefRequest(BaseModel):
    insight_id: int | None = None
    topic: str
    category: str = "Crypto Discussion"
    tone: str = "natural crypto native"
    language: str = "ru"
    format: str | None = None
    structure: list[str] = []
    examples: list[dict] = []
    cta: str | None = None
    style_limits: str | None = None


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _cls(post: ResearchPost) -> dict:
    row = next((c for c in post.classifications if c.agent_name == "combined"), None) or next(
        (c for c in post.classifications if c.agent_name == "manual"), None
    )
    if not row:
        return {}
    return {
        "niche": row.niche, "subcategories": row.subcategories_json,
        "format": row.format, "tone": row.tone, "intent": row.intent,
        "target_audience": row.target_audience_json,
        "marketing_mechanics": row.marketing_mechanics_json,
        "ctas": row.ctas_json, "confidence": row.confidence,
    }


def serialize_post(db: Session, post: ResearchPost, details: bool = False) -> dict:
    perf = post_performance(db, post)
    data = {
        "id": post.id,
        "external_post_id": post.external_post_id,
        "author": {"id": post.author.id, "username": post.author.username} if post.author else None,
        "post_url": post.post_url,
        "original_text": post.original_text,
        "language": post.language,
        "content_type": post.content_type,
        "is_reply": post.is_reply,
        "is_quote": post.is_quote,
        "has_external_link": post.has_external_link,
        "published_at": post.published_at.isoformat() if post.published_at else None,
        "created_at": post.created_at.isoformat() if post.created_at else None,
        "classification": _cls(post),
        "metrics": perf,
    }
    if details:
        from app.analytics import metrics_series

        data["metrics_history"] = metrics_series(db, post.id)
        data["comments"] = [
            {"id": c.id, "author": c.author_username, "text": c.text, "likes": c.likes}
            for c in post.comments if hasattr(post, "comments")
        ]
        links = db.scalars(select(ExternalLink).where(ExternalLink.post_id == post.id)).all()
        data["links"] = [
            {"id": l.id, "url": l.original_url, "domain": l.domain, "platform": l.platform_type,
             "utm": l.utm_json, "has_referral": l.has_referral}
            for l in links
        ]
        data["analyses"] = [
            {"agent": a.agent_name, "summary": a.summary, "confidence": a.confidence,
             "result": a.result_json, "created_at": a.created_at.isoformat() if a.created_at else None}
            for a in db.scalars(select(AiAnalysis).where(AiAnalysis.post_id == post.id)).all()
        ]
    return data


def serialize_profile(db: Session, p: TrackedProfile) -> dict:
    stats = author_leaderboard(db, "median_views", limit=1000)
    mine = next((s for s in stats if s["profile_id"] == p.id), {})
    return {
        "id": p.id, "username": p.username, "external_profile_id": p.external_profile_id,
        "profile_url": p.profile_url, "bio": p.bio, "followers": p.followers_count,
        "segment": p.segment or segment_for_followers(p.followers_count),
        "niches": p.niches_json, "language": p.language, "country": p.country,
        "added_at": p.added_at.isoformat() if p.added_at else None,
        "stats": mine,
    }


def serialize_funnel(f: Funnel) -> dict:
    return {
        "id": f.id, "product_id": f.product_id, "profile_id": f.source_profile_id,
        "entry_post_id": f.entry_post_id, "funnel_type": f.funnel_type,
        "destination_url": f.destination_url, "destination_platform": f.destination_platform,
        "description": f.funnel_description, "confidence": f.confidence_score,
        "verified_status": f.verified_status, "proof_level": f.proof_level,
        "steps": [
            {"order": s.step_order, "type": s.step_type, "description": s.description,
             "observed": s.is_observed, "proof_level": s.proof_level, "confidence": s.confidence}
            for s in f.steps
        ],
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


def serialize_product(p: Product) -> dict:
    return {
        "id": p.id, "name": p.name, "website": p.website, "domain": p.domain,
        "category": p.product_category, "type": p.product_type,
        "description": p.description, "pricing_model": p.pricing_model,
        "target_audience": p.target_audience, "landing": p.landing_analysis_json,
        "source_profile_id": p.source_profile_id,
        "first_seen_at": p.first_seen_at.isoformat() if p.first_seen_at else None,
        "last_seen_at": p.last_seen_at.isoformat() if p.last_seen_at else None,
    }


# ---------------------------------------------------------------------------
# Overview / status
# ---------------------------------------------------------------------------
@router.get("/overview", dependencies=ADMIN)
def overview(db: Session = Depends(get_db)) -> dict:
    from app.database.models import Comment

    counts = {
        "posts": count_posts(db),
        "authors": int(db.scalar(select(func.count()).select_from(TrackedProfile)) or 0),
        "products": int(db.scalar(select(func.count()).select_from(Product)) or 0),
        "links": int(db.scalar(select(func.count()).select_from(ExternalLink)) or 0),
        "funnels": int(db.scalar(select(func.count()).select_from(Funnel)) or 0),
        "insights": int(db.scalar(select(func.count()).select_from(Insight)) or 0),
        "comments": int(db.scalar(select(func.count()).select_from(Comment)) or 0),
        "reports": int(db.scalar(select(func.count()).select_from(ResearchReport)) or 0),
    }
    sources = [
        {"id": s.id, "name": s.name, "type": s.type, "enabled": s.enabled,
         "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None}
        for s in db.scalars(select(ResearchSource)).all()
    ]
    return {
        "counts": counts,
        "sources": sources,
        "niches": distribution(db, "niche"),
        "languages": distribution(db, "language"),
        "formats": distribution(db, "format"),
        "traffic": link_summary(db),
        "funnels_by_type": funnel_summary(db),
        "posts_timeline": posts_per_day(db, 30),
        "scheduler": scheduler_status(),
    }


@router.get("/sources", dependencies=ADMIN)
def list_sources(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(ResearchSource).order_by(ResearchSource.id)).all()
    return [
        {"id": s.id, "name": s.name, "type": s.type, "enabled": s.enabled,
         "config": s.config_json,
         "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None}
        for s in rows
    ]


@router.patch("/sources/{source_id}", dependencies=ADMIN)
def update_source(source_id: int, req: SourceUpdateRequest, db: Session = Depends(get_db)) -> dict:
    """Enable/disable a source or set its config (e.g. keyword_search_path)."""
    source = db.get(ResearchSource, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    if req.enabled is not None:
        source.enabled = req.enabled
    if req.config_json is not None:
        source.config_json = req.config_json
    db.flush()
    return {"id": source.id, "name": source.name, "enabled": source.enabled, "config": source.config_json}


@router.get("/status", dependencies=ADMIN)
def status(task_id: str | None = None) -> dict:
    if task_id:
        task = state.get_task(task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        return {"task": task}
    return {"latest": state.latest_task(), "recent": state.list_tasks()}


@router.get("/autopublish", dependencies=ADMIN)
def autopublish_status() -> dict:
    from app.scheduler import scheduler_status

    return scheduler_status()["auto_publish"]


@router.post("/autopublish/run", dependencies=ADMIN)
async def autopublish_run() -> dict:
    """Publish the current queue once (same code path as the scheduler)."""
    from app.scheduler import run_auto_publish

    return await run_auto_publish()


@router.post("/start", dependencies=ADMIN)
async def start_research(req: StartRequest) -> dict:
    task_id = await launch_research(req.kind, req.as_params)
    return {"task_id": task_id, "status": "running", "message": "Исследование запущено в фоне"}


@router.post("/import", dependencies=ADMIN)
async def import_data(
    req: ImportRequest | None = None,
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
) -> dict:
    import json

    items: list[dict] = []
    filename = req.filename if req else None
    if file is not None:
        content = await file.read()
        if len(content) > settings.max_import_bytes:
            raise HTTPException(413, "Import file is too large")
        filename = file.filename
        try:
            items = ManualImportSource.parse_file(file.filename or "import.json", content)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(400, f"Cannot parse import file: {exc}")
    elif req and req.content_base64:
        try:
            content = base64.b64decode(req.content_base64, validate=True)
        except ValueError:
            raise HTTPException(400, "Invalid base64 content")
        if len(content) > settings.max_import_bytes:
            raise HTTPException(413, "Import content is too large")
        items = ManualImportSource.parse_file(filename or "import.json", content)
    elif req:
        items = req.items
    else:
        raise HTTPException(400, "No data provided")

    adapter = ManualImportSource()
    get_or_create_source(db, "manual", "manual")
    stats = await collect_from_source(db, adapter, {"items": items}, source_name="manual", job_type="import")
    return {"imported": stats.get("new", 0), "duplicates": stats.get("duplicates", 0), "errors": stats.get("errors", 0)}


@router.post("/posts/manual", dependencies=ADMIN)
async def add_manual_post(req: ManualPostRequest, db: Session = Depends(get_db)) -> dict:
    item = req.model_dump(exclude_none=True)
    item["niches"] = [req.niche] if req.niche else []
    item["author_url"] = req.author_url
    adapter = ManualImportSource()
    stats = await collect_from_source(db, adapter, {"items": [item]}, job_type="manual_single")
    if stats.get("new", 0) == 0:
        # Persist the job journal even when the request ends with a 409.
        db.commit()
        raise HTTPException(409, "Post is a duplicate or could not be saved")
    return stats


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------
@router.get("/posts", dependencies=ADMIN)
def list_posts(
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = "created_at",
    order: str = "desc",
    niche: str | None = None,
    language: str | None = None,
    author_id: int | None = None,
    exclude_own: bool = False,
    min_views: int | None = None,
    has_cta: bool | None = None,
    has_link: bool | None = None,
    mechanic: str | None = None,
    days: int | None = None,
) -> dict:
    query = select(ResearchPost)
    if author_id:
        query = query.where(ResearchPost.author_id == author_id)
    if exclude_own and settings.threads_own_username:
        # Outer join retains posts with unknown authors while hiding the own profile.
        from sqlalchemy import or_
        query = query.outerjoin(TrackedProfile, TrackedProfile.id == ResearchPost.author_id).where(
            or_(TrackedProfile.id.is_(None), func.lower(TrackedProfile.username) != settings.threads_own_username)
        )
    if language:
        query = query.where(ResearchPost.language == language)
    if has_link is not None:
        query = query.where(ResearchPost.has_external_link == has_link)
    if days:
        query = query.where(ResearchPost.created_at >= utcnow() - timedelta(days=days))
    if niche or has_cta is not None or mechanic:
        query = query.join(PostClassification, PostClassification.post_id == ResearchPost.id).where(
            PostClassification.agent_name == "combined"
        )
        if niche:
            query = query.where(PostClassification.niche == niche)
        if mechanic:
            query = query.where(PostClassification.marketing_mechanics_json.contains([mechanic]))
        if has_cta is not None:
            query = query.where(PostClassification.ctas_json != [] if has_cta else PostClassification.ctas_json == [])

    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    allowed = {"created_at", "published_at", "id"}
    column = getattr(ResearchPost, sort) if sort in allowed else ResearchPost.created_at
    direction = column.desc() if order != "asc" else column.asc()
    rows = db.scalars(query.order_by(direction).offset(offset).limit(limit)).all()

    results = []
    for p in rows:
        data = serialize_post(db, p)
        if min_views is not None and (data["metrics"]["views"] or 0) < min_views:
            continue
        results.append(data)
    return {"total": total, "limit": limit, "offset": offset, "items": results}


@router.get("/posts/{post_id}", dependencies=ADMIN)
def get_post(post_id: int, db: Session = Depends(get_db)) -> dict:
    post = db.get(ResearchPost, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    return serialize_post(db, post, details=True)


@router.post("/posts/{post_id}/metric", dependencies=ADMIN)
def add_post_metric(post_id: int, payload: dict, db: Session = Depends(get_db)) -> dict:
    post = db.get(ResearchPost, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    m = add_metric(
        db, post.id,
        views=payload.get("views"), likes=payload.get("likes"),
        replies=payload.get("replies"), reposts=payload.get("reposts"),
        quotes=payload.get("quotes"), data_source=payload.get("data_source", "manual"),
        is_estimated=bool(payload.get("is_estimated", False)),
    )
    return {"id": m.id, "engagement_rate": m.engagement_rate}


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------
@router.get("/profiles", dependencies=ADMIN)
def list_profiles(db: Session = Depends(get_db), limit: int = 100) -> list[dict]:
    rows = db.scalars(select(TrackedProfile).order_by(TrackedProfile.added_at.desc()).limit(limit)).all()
    return [serialize_profile(db, p) for p in rows]


@router.post("/profiles", dependencies=ADMIN)
def add_profile(req: ProfileRequest, db: Session = Depends(get_db)) -> dict:
    from app.utils import segment_for_followers

    src = get_or_create_source(db, "manual", "manual")
    profile, _ = get_or_create_profile(
        db, req.username, source_id=src.id, profile_url=req.profile_url,
        bio=req.bio, followers_count=req.followers_count,
        niches=req.niches, language=req.language,
    )
    if req.external_profile_id:
        profile.external_profile_id = req.external_profile_id
    profile.segment = segment_for_followers(req.followers_count)
    db.flush()
    return serialize_profile(db, profile)


@router.post("/profiles/import", dependencies=ADMIN)
async def import_profiles(
    req: ProfileImportRequest | None = None,
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Bulk-add tracked authors from JSON/CSV (no one-by-one form filling)."""
    import csv
    import io

    items: list[dict] = []
    if file is not None:
        content = await file.read()
        if len(content) > settings.max_import_bytes:
            raise HTTPException(413, "Import file is too large")
        text = content.decode("utf-8-sig")
        if (file.filename or "").lower().endswith(".json"):
            import json

            data = json.loads(text)
            items = data if isinstance(data, list) else data.get("items", [])
        else:
            items = list(csv.DictReader(io.StringIO(text)))
    elif req:
        items = req.items
    else:
        raise HTTPException(400, "No profiles provided")

    from app.utils import segment_for_followers

    src = get_or_create_source(db, "manual", "manual")
    created = 0
    for item in items:
        username = str(item.get("username") or item.get("author") or "").strip().lstrip("@")
        if not username:
            continue
        try:
            followers = int(float(str(item.get("followers_count") or item.get("followers") or 0)))
        except (ValueError, TypeError):
            followers = None
        niches = item.get("niches") or []
        if isinstance(niches, str):
            niches = [n.strip() for n in niches.split("|") if n.strip()]
        profile, is_new = get_or_create_profile(
            db, username,
            source_id=src.id,
            profile_url=item.get("profile_url"),
            bio=item.get("bio"),
            followers_count=followers,
            niches=niches,
            language=item.get("language"),
        )
        profile.external_profile_id = item.get("external_profile_id") or item.get("threads_user_id") or profile.external_profile_id
        profile.segment = segment_for_followers(followers)
        created += int(is_new)
    db.flush()
    return {"added": created, "total": len(items)}


@router.get("/authors/leaderboard", dependencies=ADMIN)
def leaderboard(metric: str = "median_views", limit: int = 20, db: Session = Depends(get_db)) -> list[dict]:
    return author_leaderboard(db, metric, limit)


# ---------------------------------------------------------------------------
# Funnels / Products / Links
# ---------------------------------------------------------------------------
@router.get("/funnels", dependencies=ADMIN)
def list_funnels(
    db: Session = Depends(get_db),
    funnel_type: str | None = None,
    proof_level: str | None = None,
    limit: int = 100,
) -> list[dict]:
    query = select(Funnel)
    if funnel_type:
        query = query.where(Funnel.funnel_type == funnel_type)
    if proof_level:
        query = query.where(Funnel.proof_level == proof_level)
    rows = db.scalars(query.order_by(Funnel.created_at.desc()).limit(limit)).all()
    return [serialize_funnel(f) for f in rows]


@router.get("/products", dependencies=ADMIN)
def list_products(db: Session = Depends(get_db), limit: int = 100) -> list[dict]:
    rows = db.scalars(select(Product).order_by(Product.last_seen_at.desc()).limit(limit)).all()
    return [serialize_product(p) for p in rows]


@router.get("/links", dependencies=ADMIN)
def list_links(db: Session = Depends(get_db), limit: int = 200) -> list[dict]:
    rows = db.scalars(select(ExternalLink).order_by(ExternalLink.detected_at.desc()).limit(limit)).all()
    return [
        {"id": l.id, "url": l.original_url, "domain": l.domain, "platform": l.platform_type,
         "post_id": l.post_id, "profile_id": l.profile_id, "product_id": l.product_id,
         "utm": l.utm_json, "has_referral": l.has_referral,
         "is_accessible": l.is_accessible, "detected_at": l.detected_at.isoformat() if l.detected_at else None}
        for l in rows
    ]


@router.post("/landing", dependencies=ADMIN)
async def analyze_landing(payload: dict) -> dict:
    from app.ai.funnel_analyzer import analyze_landing as _analyze

    url = payload.get("url", "")
    card = await _analyze(url)
    if card.get("error"):
        raise HTTPException(422, f"Landing analysis failed: {card['error']}")
    return card


@router.get("/tracked-url", dependencies=ADMIN)
def tracked_url(post_id: int, campaign: str | None = None) -> dict:
    if not settings.base_referral_url:
        raise HTTPException(400, "BASE_REFERRAL_URL is not configured")
    return {"url": build_tracked_url(settings.base_referral_url, post_id, campaign)}


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------
@router.post("/analyze", dependencies=ADMIN)
async def analyze(req: AnalyzeRequest, db: Session = Depends(get_db)) -> dict:
    if req.post_id:
        from app.ai.tasks import analyze_post

        post = db.get(ResearchPost, req.post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        result = await analyze_post(db, post, force=req.force)
        return {"post_id": req.post_id, "result": result}
    task_id = await launch_analysis(req.limit)
    return {"task_id": task_id, "status": "running"}


@router.post("/profiles/{profile_id}/analyze", dependencies=ADMIN)
async def analyze_author(profile_id: int, db: Session = Depends(get_db)) -> dict:
    from app.ai.tasks import analyze_profile_agent
    from app.analytics import author_stats

    profile = db.get(TrackedProfile, profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    data = author_stats(db, profile)
    result = await analyze_profile_agent(db, profile, data)
    return {"profile_id": profile_id, "result": result}


@router.get("/insights", dependencies=ADMIN)
def list_insights(db: Session = Depends(get_db), limit: int = 100) -> list[dict]:
    rows = db.scalars(select(Insight).order_by(Insight.created_at.desc()).limit(limit)).all()
    return [
        {"id": i.id, "title": i.title, "description": i.description, "niche": i.niche,
         "sample_size": i.sample_size, "period_from": i.period_from.isoformat() if i.period_from else None,
         "period_to": i.period_to.isoformat() if i.period_to else None, "metrics": i.metrics_json,
         "examples": i.example_post_ids_json, "limitations": i.limitations,
         "confidence": i.confidence, "evidence": i.evidence_json}
        for i in rows
    ]


@router.post("/insights", dependencies=ADMIN)
def add_insight(req: InsightRequest, db: Session = Depends(get_db)) -> dict:
    from app.database.models import Insight as InsightModel

    insight = InsightModel(
        title=req.title, description=req.description, niche=req.niche,
        sample_size=req.sample_size, confidence=req.confidence,
        example_post_ids_json=req.example_post_ids, limitations=req.limitations,
        evidence_json=req.evidence, created_at=utcnow(),
    )
    db.add(insight)
    db.flush()
    return {"id": insight.id}


# ---------------------------------------------------------------------------
# Experiments & Writer integration
# ---------------------------------------------------------------------------
@router.get("/experiments", dependencies=ADMIN)
def list_experiments(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Experiment).order_by(Experiment.created_at.desc())).all()
    return [
        {"id": e.id, "name": e.name, "hypothesis": e.hypothesis, "status": e.status,
         "niche": e.niche, "format": e.format, "cta": e.cta,
         "planned_posts": e.planned_posts, "results": e.results_json}
        for e in rows
    ]


@router.post("/experiments", dependencies=ADMIN)
def add_experiment(req: ExperimentRequest, db: Session = Depends(get_db)) -> dict:
    exp = Experiment(
        name=req.name, hypothesis=req.hypothesis, niche=req.niche,
        format=req.format, cta=req.cta, planned_posts=req.planned_posts,
        created_at=utcnow(),
    )
    db.add(exp)
    db.flush()
    return {"id": exp.id}


@router.post("/briefs/{brief_id}/generate", dependencies=ADMIN)
async def generate_from_brief(brief_id: int, db: Session = Depends(get_db)) -> dict:
    """Turn a research brief into a real Writer draft (still needs manual approval)."""
    from app.writer_service import generate_text

    brief = db.get(WriterBrief, brief_id)
    if not brief:
        raise HTTPException(404, "Brief not found")
    text = await generate_text(
        topic=brief.topic,
        category=brief.category,
        tone=brief.tone,
        language=brief.language,
        structure=brief.structure_json,
        examples=brief.examples_json,
        cta=brief.cta,
        style_limits=brief.style_limits,
        post_format=brief.format,
    )
    if len(text) > 500:
        raise HTTPException(502, "AI выдал текст длиннее 500 символов")
    post = WriterPost(
        text=text,
        category=brief.category,
        language=(brief.language or "ru")[:20],
        status="pending_review",
    )
    db.add(post)
    db.flush()
    brief.status = "used"
    return {
        "id": post.id,
        "text": text,
        "language": post.language,
        "category": post.category,
        "status": post.status,
        "message": "Черновик создан в Writer. Требуется ручное одобрение.",
    }


@router.get("/briefs", dependencies=ADMIN)
def list_briefs(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(WriterBrief).order_by(WriterBrief.created_at.desc())).all()
    return [
        {"id": b.id, "insight_id": b.insight_id, "topic": b.topic, "category": b.category,
         "tone": b.tone, "language": getattr(b, "language", "ru") or "ru",
         "format": b.format, "structure": b.structure_json,
         "examples": b.examples_json, "cta": b.cta, "style_limits": b.style_limits,
         "status": b.status}
        for b in rows
    ]


@router.post("/briefs", dependencies=ADMIN)
def add_brief(req: BriefRequest, db: Session = Depends(get_db)) -> dict:
    brief = WriterBrief(
        insight_id=req.insight_id, topic=req.topic, category=req.category,
        tone=req.tone, language=(req.language or "ru")[:20],
        format=req.format, structure_json=req.structure,
        examples_json=req.examples, cta=req.cta, style_limits=req.style_limits,
        created_at=utcnow(),
    )
    db.add(brief)
    db.flush()
    return {"id": brief.id, "message": "Бриф передан в Writer (Existing AI Writer)"}


# ---------------------------------------------------------------------------
# Reports & jobs
# ---------------------------------------------------------------------------
@router.post("/reports", dependencies=ADMIN)
async def create_report(req: ReportRequest, db: Session = Depends(get_db)) -> dict:
    if count_posts(db) == 0:
        raise HTTPException(
            409,
            "Нет публикаций для отчёта. Сначала импортируйте данные "
            "(Data & Jobs → импорт JSON/CSV) или запустите сбор с доступными источниками.",
        )
    report = await build_report(
        db, title=req.title, report_type=req.report_type, days=req.days
    )
    return {"id": report.id, "title": report.title}


@router.post("/reports/generate", dependencies=ADMIN)
async def generate_report_async(req: ReportRequest) -> dict:
    task_id = await launch_report(req.days)
    return {"task_id": task_id, "status": "running"}


@router.get("/reports", dependencies=ADMIN)
def list_reports(db: Session = Depends(get_db), limit: int = 50) -> list[dict]:
    rows = db.scalars(select(ResearchReport).order_by(ResearchReport.created_at.desc()).limit(limit)).all()
    return [
        {"id": r.id, "title": r.title, "type": r.report_type,
         "created_at": r.created_at.isoformat() if r.created_at else None,
         "period_from": r.period_from.isoformat() if r.period_from else None,
         "period_to": r.period_to.isoformat() if r.period_to else None}
        for r in rows
    ]


@router.get("/reports/{report_id}", dependencies=ADMIN)
def get_report(report_id: int, db: Session = Depends(get_db)) -> dict:
    report = db.get(ResearchReport, report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    return {
        "id": report.id, "title": report.title, "content_md": report.content_md,
        "content_html": report.content_html, "summary": report.summary_json,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.delete("/reports/{report_id}", dependencies=ADMIN)
def delete_report(report_id: int, db: Session = Depends(get_db)) -> dict:
    report = db.get(ResearchReport, report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    db.delete(report)
    db.flush()
    return {"deleted": report_id}


@router.get("/reports/{report_id}/export", dependencies=ADMIN)
def export_report(report_id: int, format: str = "markdown", db: Session = Depends(get_db)):
    from fastapi.responses import HTMLResponse, PlainTextResponse, Response

    report = db.get(ResearchReport, report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    fmt = format.lower()
    if fmt == "json":
        return report.summary_json
    if fmt == "csv":
        rows = []
        for pid in report.summary_json.get("facts", {}).get("example_post_ids", []):
            post = db.get(ResearchPost, pid)
            if post:
                rows.append(serialize_post(db, post))
        return PlainTextResponse(posts_to_csv(rows), media_type="text/csv")
    if fmt == "pdf":
        return Response(
            render_pdf(report.title, report.content_md),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="report-{report_id}.pdf"'},
        )
    if fmt == "html":
        return HTMLResponse(report.content_html)
    return PlainTextResponse(report.content_md, media_type="text/markdown")


@router.get("/backup", dependencies=ADMIN)
def backup_database(db: Session = Depends(get_db)):
    from fastapi.responses import Response
    from app.database.backup import create_backup

    try:
        data, filename = create_backup(db)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    return Response(
        data,
        media_type="application/sql",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/posts/{post_id}", dependencies=ADMIN)
def delete_post(post_id: int, db: Session = Depends(get_db)) -> dict:
    """Remove research data for one post (right-to-erasure / cleanup)."""
    post = db.get(ResearchPost, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    for model in [PostMetricModel, CommentModel, ExternalLink, PostClassificationModel, AiAnalysis]:
        for row in db.scalars(select(model).where(model.post_id == post_id)).all():
            db.delete(row)
    for funnel in db.scalars(select(Funnel).where(Funnel.entry_post_id == post_id)).all():
        for step in db.scalars(select(FunnelStep).where(FunnelStep.funnel_id == funnel.id)).all():
            db.delete(step)
        db.delete(funnel)
    db.delete(post)
    db.flush()
    return {"deleted": post_id}


@router.delete("/profiles/{profile_id}", dependencies=ADMIN)
def delete_profile(profile_id: int, db: Session = Depends(get_db)) -> dict:
    profile = db.get(TrackedProfile, profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    for post in db.scalars(select(ResearchPost).where(ResearchPost.author_id == profile_id)).all():
        db.delete(post)
    db.delete(profile)
    db.flush()
    return {"deleted": profile_id}


@router.get("/jobs", dependencies=ADMIN)
def list_jobs(
    db: Session = Depends(get_db),
    limit: int = 50,
    source_id: int | None = None,
    status: str | None = None,
) -> list[dict]:
    query = select(CollectionJob)
    if source_id:
        query = query.where(CollectionJob.source_id == source_id)
    if status:
        query = query.where(CollectionJob.status == status)
    rows = db.scalars(query.order_by(CollectionJob.started_at.desc()).limit(limit)).all()
    return [
        {"id": j.id, "source_id": j.source_id, "type": j.job_type, "status": j.status,
         "started_at": j.started_at.isoformat() if j.started_at else None,
         "finished_at": j.finished_at.isoformat() if j.finished_at else None,
         "found": j.found_count, "new": j.new_count, "duplicates": j.duplicate_count,
         "errors": j.error_count, "error_message": j.error_message, "error_log": j.error_log_json}
        for j in rows
    ]
