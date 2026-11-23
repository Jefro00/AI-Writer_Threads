"""Assemble a research report from stored observations and AI insights."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import report_generator
from app.database.models import (
    AiAnalysis,
    ExternalLink,
    Funnel,
    Insight,
    PostClassification,
    ResearchPost,
    ResearchReport,
    TrackedProfile,
    utcnow,
)
from app.database.repository import count_posts


async def build_report(
    db: Session,
    *,
    title: str = "Threads Research Report",
    report_type: str = "weekly",
    days: int = 30,
    niche: str | None = None,
    language: str | None = None,
) -> ResearchReport:
    since = utcnow() - timedelta(days=days)
    posts = db.scalars(select(ResearchPost).where(ResearchPost.created_at >= since)).all()
    post_ids = [p.id for p in posts]
    classifications = db.scalars(
        select(PostClassification).where(
            PostClassification.post_id.in_(post_ids),
            PostClassification.agent_name.in_(["combined", "manual"]),
        )
    ).all() if post_ids else []
    funnels = db.scalars(select(Funnel)).all()
    links = db.scalars(select(ExternalLink)).all()
    insights = db.scalars(select(Insight)).all()
    profiles = db.scalars(select(TrackedProfile)).all()

    # One classification per post: prefer the AI result, fall back to manual.
    ai_by_post = {c.post_id: c for c in classifications if c.agent_name == "combined"}
    manual_by_post = {c.post_id: c for c in classifications if c.agent_name == "manual"}
    chosen = [ai_by_post.get(pid) or manual_by_post.get(pid) for pid in post_ids]

    niches: dict[str, int] = {}
    languages: dict[str, int] = {}
    mechanics: dict[str, int] = {}
    for c in chosen:
        if not c:
            continue
        if c.niche:
            niches[c.niche] = niches.get(c.niche, 0) + 1
        if c.language:
            languages[c.language] = languages.get(c.language, 0) + 1
        for m in c.marketing_mechanics_json or []:
            mechanics[str(m)] = mechanics.get(str(m), 0) + 1

    facts = {
        "total_posts": len(posts),
        "total_authors": len(profiles),
        "total_links": len(links),
        "total_funnels": len(funnels),
        "niches": niches,
        "languages": languages,
        "mechanics": mechanics,
        "insights": [
            {"title": i.title, "description": i.description, "sample": i.sample_size, "confidence": i.confidence}
            for i in insights[:10]
        ],
        "example_post_ids": post_ids[:10],
        "limitations": [
            "Чужие конверсии, продажи и выручка недоступны через публичные источники.",
            "Все метрики поступают от источника и не оцениваются AI.",
            "Воронки L6/L7 требуют собственной аналитики автора.",
        ],
    }
    narrative = await report_generator.generate(facts)
    ai_failed = not narrative.get("patterns") or narrative.get("limitations") == ["AI unavailable"]
    if ai_failed:
        # Deterministic, fact-based fallback: never leave an empty report just
        # because a free AI provider was temporarily unavailable.
        top_mechanic = max(mechanics.items(), key=lambda x: x[1])[0] if mechanics else None
        top_niche = max(niches.items(), key=lambda x: x[1])[0] if niches else None
        narrative["patterns"] = [
            f"В выборке {len(posts)} публикаций от {len(profiles)} авторов.",
            (f"Наиболее частая маркетинговая механика: {top_mechanic} ({mechanics[top_mechanic]})." if top_mechanic else "Маркетинговые механики не обнаружены."),
            (f"Основная ниша выборки: {top_niche}." if top_niche else "Ниши не определены."),
            f"Обнаружено воронок: {len(funnels)}, внешних ссылок: {len(links)}.",
        ]
        narrative["recommendations"] = [
            (f"Протестировать механику {top_mechanic} на собственном аккаунте и сравнить медианы." if top_mechanic else "Сначала собрать больше публикаций для выявления механик."),
            "Увеличить выборку минимум до 30 публикаций на нишу перед выводами.",
            "Проверить воронки L6/L7 только через собственную аналитику или добровольные кейсы авторов.",
        ]
        narrative["examples"] = [
            {"post_id": pid, "why": "Пример из исследованной выборки; проверить исходный текст и метрики."}
            for pid in post_ids[:5]
        ]
        narrative["limitations"] = facts["limitations"] + [
            "AI-нарратив временно недоступен; разделы сформированы из наблюдаемых фактов."
        ]
        narrative["confidence"] = 0.3
    from .markdown import render_markdown
    from .html import render_html

    md = render_markdown(title, facts, narrative)
    report = ResearchReport(
        title=title,
        report_type=report_type,
        period_from=since,
        period_to=utcnow(),
        filters_json={"days": days, "niche": niche, "language": language},
        content_md=md,
        content_html=render_html(title, md),
        summary_json={"facts": facts, "narrative": narrative},
        created_at=utcnow(),
    )
    db.add(report)
    db.flush()
    return report
