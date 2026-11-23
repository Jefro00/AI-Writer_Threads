"""ORM models.

NOTE ON NAMING: the starter project already owns the ``posts`` table (the
Writer's own drafts). To avoid any regression the research publications live in
``research_posts``. Everything else follows the names from the technical spec.

Naive UTC datetimes are used consistently across the research tables so
comparisons never mix aware and naive values on SQLite/PostgreSQL.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Existing Writer model (kept verbatim in behaviour, moved here for a single
# shared Base.metadata).
# ---------------------------------------------------------------------------
class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="Crypto Discussion")
    language: Mapped[str] = mapped_column(String(20), default="ru")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    threads_post_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("writer_campaigns.id"), nullable=True)
    offer_id: Mapped[int | None] = mapped_column(ForeignKey("affiliate_offers.id"), nullable=True)
    goal: Mapped[str] = mapped_column(String(30), default="discussion")
    hook_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    variant_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    editorial_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tracking_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)



# ---------------------------------------------------------------------------
# Affiliate growth: offers, batches, anonymized click totals and manual metrics.
# ---------------------------------------------------------------------------
class AffiliateOffer(Base):
    __tablename__ = "affiliate_offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    referral_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    target_audience: Mapped[str] = mapped_column(Text, default="")
    benefits_json: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WriterCampaign(Base):
    __tablename__ = "writer_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    language: Mapped[str] = mapped_column(String(20), default="ru")
    goal: Mapped[str] = mapped_column(String(30), default="clicks")
    offer_id: Mapped[int | None] = mapped_column(ForeignKey("affiliate_offers.id"), nullable=True)
    hook_type: Mapped[str] = mapped_column(String(40), default="auto")
    promotion_style: Mapped[str] = mapped_column(String(30), default="soft")
    prompt_version: Mapped[str] = mapped_column(String(40), default="growth-v1")
    hooks_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReferralClick(Base):
    __tablename__ = "referral_clicks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("affiliate_offers.id"), nullable=False)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Only event timestamp / offer / post. No IP, cookie or fingerprint recorded.
    __table_args__ = (Index("ix_referral_clicks_post", "post_id"),)


class WriterPostMetrics(Base):
    __tablename__ = "writer_post_metrics"

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), primary_key=True)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    replies: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reposts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    registrations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="manual")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Sources & collection
# ---------------------------------------------------------------------------
class ResearchSource(Base):
    __tablename__ = "research_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)  # manual|threads_api|content_library|account_monitor
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CollectionJob(Base):
    __tablename__ = "collection_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("research_sources.id"), nullable=True)
    job_type: Mapped[str] = mapped_column(String(60), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|success|partial|failed
    params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    found_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_log_json: Mapped[list] = mapped_column(JSON, default=list)


# ---------------------------------------------------------------------------
# Profiles (tracked authors)
# ---------------------------------------------------------------------------
class TrackedProfile(Base):
    __tablename__ = "tracked_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("research_sources.id"), nullable=True)
    username: Mapped[str] = mapped_column(String(150), nullable=False)
    external_profile_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    profile_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    followers_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    niches_json: Mapped[list] = mapped_column(JSON, default=list)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    advertised_products_json: Mapped[list] = mapped_column(JSON, default=list)
    segment: Mapped[str | None] = mapped_column(String(20), nullable=True)  # micro/small/medium/large/very_large
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    observations: Mapped[list["ProfileObservation"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("username", name="uq_profile_username"),)


class ProfileObservation(Base):
    """History of profile observations (followers, bio, strategy changes)."""

    __tablename__ = "profile_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("tracked_profiles.id"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    followers_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)

    profile: Mapped[TrackedProfile] = relationship(back_populates="observations")


# ---------------------------------------------------------------------------
# Publications, metrics, comments
# ---------------------------------------------------------------------------
class ResearchPost(Base):
    __tablename__ = "research_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("research_sources.id"), nullable=True)
    external_post_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("tracked_profiles.id"), nullable=True)
    post_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    translated_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # for display/AI only
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    is_quote: Mapped[bool] = mapped_column(Boolean, default=False)
    has_external_link: Mapped[bool] = mapped_column(Boolean, default=False)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    author: Mapped[TrackedProfile | None] = relationship("TrackedProfile")
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )
    metrics: Mapped[list["PostMetric"]] = relationship(
        back_populates="post", cascade="all, delete-orphan", order_by="PostMetric.collected_at"
    )
    classifications: Mapped[list["PostClassification"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("source_id", "external_post_id", name="uq_post_source_external"),
        Index("ix_research_posts_hash", "text_hash"),
        Index("ix_research_posts_published", "published_at"),
    )


class PostMetric(Base):
    __tablename__ = "post_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("research_posts.id"), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    replies: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reposts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quotes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engagement_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    is_estimated: Mapped[bool] = mapped_column(Boolean, default=False)

    post: Mapped[ResearchPost] = relationship(back_populates="metrics")

    __table_args__ = (Index("ix_post_metrics_post_collected", "post_id", "collected_at"),)


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("research_posts.id"), nullable=False)
    post: Mapped[ResearchPost] = relationship(back_populates="comments")
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    author_username: Mapped[str | None] = mapped_column(String(150), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Products, links, funnels
# ---------------------------------------------------------------------------
class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    website: Mapped[str | None] = mapped_column(String(600), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(200), nullable=True)
    product_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    product_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    pricing_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    target_audience: Mapped[list] = mapped_column(JSON, default=list)
    landing_analysis_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_profile_id: Mapped[int | None] = mapped_column(ForeignKey("tracked_profiles.id"), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("domain", "name", name="uq_product_domain_name"),)


class ExternalLink(Base):
    __tablename__ = "external_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("research_posts.id"), nullable=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("tracked_profiles.id"), nullable=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str | None] = mapped_column(String(200), nullable=True)
    platform_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    destination_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    redirect_chain_json: Mapped[list] = mapped_column(JSON, default=list)
    utm_json: Mapped[dict] = mapped_column(JSON, default=dict)
    has_referral: Mapped[bool] = mapped_column(Boolean, default=False)
    is_accessible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Funnel(Base):
    __tablename__ = "funnels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    source_profile_id: Mapped[int | None] = mapped_column(ForeignKey("tracked_profiles.id"), nullable=True)
    entry_post_id: Mapped[int | None] = mapped_column(ForeignKey("research_posts.id"), nullable=True)
    funnel_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    destination_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    destination_platform: Mapped[str | None] = mapped_column(String(60), nullable=True)
    funnel_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    verified_status: Mapped[str] = mapped_column(String(20), default="unverified")  # unverified|observed|verified
    proof_level: Mapped[str] = mapped_column(String(4), default="L1")  # L1..L7
    steps_json: Mapped[list] = mapped_column(JSON, default=list)
    evidence_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    steps: Mapped[list["FunnelStep"]] = relationship(
        back_populates="funnel", cascade="all, delete-orphan", order_by="FunnelStep.step_order"
    )


class FunnelStep(Base):
    __tablename__ = "funnel_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    funnel_id: Mapped[int] = mapped_column(ForeignKey("funnels.id"), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, default=0)
    step_type: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    is_observed: Mapped[bool] = mapped_column(Boolean, default=False)  # L1-L5 observed, L6-L7 assumed
    proof_level: Mapped[str] = mapped_column(String(4), default="L1")

    funnel: Mapped[Funnel] = relationship(back_populates="steps")


# ---------------------------------------------------------------------------
# Taxonomy & AI
# ---------------------------------------------------------------------------
class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    niche: Mapped[str | None] = mapped_column(String(80), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (UniqueConstraint("name", "niche", name="uq_category_name_niche"),)


class PostClassification(Base):
    """One agent's structured classification of a post (multi-label)."""

    __tablename__ = "post_classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("research_posts.id"), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(60), nullable=False)
    niche: Mapped[str | None] = mapped_column(String(80), nullable=True)
    subcategories_json: Mapped[list] = mapped_column(JSON, default=list)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    format: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    intent: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_audience_json: Mapped[list] = mapped_column(JSON, default=list)
    marketing_mechanics_json: Mapped[list] = mapped_column(JSON, default=list)
    ctas_json: Mapped[list] = mapped_column(JSON, default=list)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    post: Mapped[ResearchPost] = relationship(back_populates="classifications")

    __table_args__ = (
        UniqueConstraint("post_id", "agent_name", "prompt_version", name="uq_post_agent_prompt"),
    )


class AiAnalysis(Base):
    """Raw, versioned AI analysis with the source data it was derived from.

    ``input_hash`` + ``prompt_version`` guarantee that re-analysis only happens
    when the text or the prompt actually changed.
    """

    __tablename__ = "ai_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("research_posts.id"), nullable=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("tracked_profiles.id"), nullable=True)
    agent_name: Mapped[str] = mapped_column(String(60), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_data_json: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("input_hash", "prompt_version", "agent_name", name="uq_ai_input_prompt_agent"),
        Index("ix_ai_analysis_agent", "agent_name"),
    )


class Insight(Base):
    """A verifiable marketing hypothesis produced from a set of observations."""

    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    niche: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    period_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    period_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    example_post_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    limitations: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ResearchReport(Base):
    __tablename__ = "research_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    report_type: Mapped[str] = mapped_column(String(40), default="weekly")
    period_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    period_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    filters_json: Mapped[dict] = mapped_column(JSON, default=dict)
    content_md: Mapped[str] = mapped_column(Text, default="")
    content_html: Mapped[str] = mapped_column(Text, default="")
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Experiment(Base):
    """Own tests run on the JefroCrypto account (Strategy Testing Lab)."""

    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="planned")  # planned|running|finished
    niche: Mapped[str | None] = mapped_column(String(80), nullable=True)
    format: Mapped[str | None] = mapped_column(String(60), nullable=True)
    cta: Mapped[str | None] = mapped_column(String(120), nullable=True)
    target_audience_json: Mapped[list] = mapped_column(JSON, default=list)
    planned_posts: Mapped[int] = mapped_column(Integer, default=10)
    results_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WriterBrief(Base):
    """A research insight handed over to the existing Writer."""

    __tablename__ = "writer_briefs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    insight_id: Mapped[int | None] = mapped_column(ForeignKey("insights.id"), nullable=True)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="Crypto Discussion")
    tone: Mapped[str] = mapped_column(String(120), default="natural crypto native")
    language: Mapped[str] = mapped_column(String(20), default="en")
    format: Mapped[str | None] = mapped_column(String(60), nullable=True)
    structure_json: Mapped[list] = mapped_column(JSON, default=list)
    examples_json: Mapped[list] = mapped_column(JSON, default=list)
    cta: Mapped[str | None] = mapped_column(String(300), nullable=True)
    style_limits: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
