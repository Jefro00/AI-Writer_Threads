"""Style intelligence from licensed/available research posts, without model training.

The pattern library stores reusable editorial abstractions and provenance.
Scores based on observed metrics are *descriptive*, not predicted CTR.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from statistics import median
from sqlalchemy import select

from app.database.models import ResearchPost, TrackedProfile, PostMetric, StylePattern, PostClassification
from app.config import settings

STOP = {"почему", "люди", "этот", "когда", "сейчас", "пост", "очень", "такие", "после", "crypto", "about", "which", "that", "this", "with", "their", "your", "много", "просто", "новый", "можно", "будет"}


def tokens(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-zа-яё0-9]{3,}", (text or "").casefold()) if x not in STOP}


def classify_hook(text: str) -> tuple[str, str, str, str, list[str]]:
    line = next((s.strip() for s in text.splitlines() if s.strip()), "")[:180]
    low = line.casefold()
    if any(x in low for x in (" vs ", "против ", "или ", "лучше чем", "сравни")):
        kind, structure, emotion = "comparison", "сравнение → неожиданное различие → вывод", "контраст"
    elif any(x in low for x in ("ошибка", "слил", "потер", "поздно", "боль", "устал", "проблем")):
        kind, structure, emotion = "pain_point", "знакомая боль → конкретное наблюдение → вопрос", "узнавание"
    elif any(x in low for x in ("никто", "на самом деле", "все дума", "не потому", "миф")):
        kind, structure, emotion = "contrarian", "массовое убеждение → контраст → новый взгляд", "удивление"
    elif "?" in line or any(x in low for x in ("что если", "знаешь", "секрет", "как так")):
        kind, structure, emotion = "curiosity", "открытый вопрос → ответ/наблюдение → вопрос к аудитории", "любопытство"
    elif any(x in low for x in ("я заметил", "вчера", "однажды", "помню", "история")):
        kind, structure, emotion = "story", "ситуация → поворот → вывод", "сопереживание"
    else:
        kind, structure, emotion = "debate", "короткий тезис → аргумент → открытый вопрос", "дискуссия"
    tags = []
    if len(line.split()) <= 12: tags.append("короткое начало")
    if "?" in text: tags.append("вопрос")
    if len(text.splitlines()) > 2: tags.append("короткие абзацы")
    if re.search(r"[!?]{2}|🚀|🔥", text): tags.append("эмоциональная пунктуация")
    if re.search(r"\b(я|мне|мой|I|my)\b", text, re.I): tags.append("от первого лица")
    return kind, structure, emotion, "разговорный" if len(line) < 120 else "развёрнутый", tags


def _self_username() -> str:
    return (getattr(settings, "threads_own_username", "") or "").lstrip("@").casefold()


def _latest_metrics(db, post_id: int) -> PostMetric | None:
    return db.scalars(select(PostMetric).where(PostMetric.post_id == post_id).order_by(PostMetric.collected_at.desc(), PostMetric.id.desc()).limit(1)).first()


def rebuild_patterns(db, *, limit: int = 300) -> dict:
    """Idempotent, non-generative extraction; auto excludes own author and replies.

    Only adds missing patterns. Doesn't overwrite user-disabled pattern choices.
    """
    own = _self_username()
    rows = db.scalars(select(ResearchPost).order_by(ResearchPost.created_at.desc()).limit(limit)).all()
    added = 0
    excluded = 0
    for p in rows:
        author = db.get(TrackedProfile, p.author_id) if p.author_id else None
        if (author and own and author.username.lstrip("@").casefold() == own) or p.is_reply:
            excluded += 1
            continue
        if not author or not author.username or len(p.original_text.strip()) < 35:
            excluded += 1
            continue
        existing = db.scalar(select(StylePattern.id).where(StylePattern.source_post_id == p.id))
        if existing:
            continue
        kind, structure, emotion, tone, tags = classify_hook(p.original_text)
        # Original text is NOT stored in StylePattern; see provenance post_id.
        cl = db.scalars(select(PostClassification).where(PostClassification.post_id == p.id).order_by(PostClassification.id.desc())).first()
        if cl and cl.tone: tone = cl.tone[:80]
        metric = _latest_metrics(db, p.id)
        views = metric.views if metric and not metric.is_estimated else None
        engagement = sum((getattr(metric, field) or 0) for field in ("likes", "replies", "reposts")) if metric else None
        pattern = StylePattern(source_post_id=p.id, source_author=author.username[:150], language=p.language or "ru",
                               hook_type=kind, tone=tone, structure=structure, emotion=emotion,
                               tags_json=tags, topic_tags_json=sorted(tokens(p.original_text))[:35],
                               observed_views=views, observed_engagement=engagement,
                               enabled=True)
        db.add(pattern)
        added += 1
    db.flush()
    return {"added": added, "excluded": excluded, "processed": len(rows)}


def rank_patterns(db, *, topic: str, language: str = "ru", limit: int = 5, style: str = "mixed") -> list[dict]:
    patterns = db.scalars(select(StylePattern).where(StylePattern.enabled.is_(True)).limit(1500)).all()
    own = _self_username()
    patterns = [p for p in patterns if not (own and p.source_author.lstrip("@").casefold() == own)]
    if not patterns: return []
    # Observed author baselines from comparable, non-estimated posts.
    author_views: dict[str, list[int]] = {}
    for p in patterns:
        if p.observed_views and p.observed_views > 0:
            author_views.setdefault(p.source_author, []).append(p.observed_views)
    baselines = {a: median(v) for a, v in author_views.items() if len(v) >= 3}
    q = tokens(topic)
    ranked = []
    for p in patterns:
        overlap = len(q.intersection(set(p.topic_tags_json or [])))
        similar = overlap / max(1, len(q))
        baseline = baselines.get(p.source_author)
        lift = (p.observed_views / baseline) if baseline and p.observed_views is not None else None
        # No artificial 10/10 virality score; capped measured lift and lexical relevance.
        score = similar * 5 + (1 if p.language == language else 0) + (min(2, math.log2(max(lift, 1))) if lift else 0)
        if style != "mixed" and style in (p.tone or "").casefold(): score += 1
        ranked.append((score, p, lift, overlap))
    ranked.sort(key=lambda r: (r[0], r[3], r[1].id), reverse=True)
    output, authors, kinds = [], Counter(), Counter()
    for score, p, lift, overlap in ranked:
        if authors[p.source_author] >= 2 or (kinds[p.hook_type] >= 2 and len(output) < limit - 1):
            continue
        output.append({"id": p.id, "source_post_id": p.source_post_id, "author": p.source_author,
                       "hook_type": p.hook_type, "tone": p.tone, "structure": p.structure,
                       "emotion": p.emotion, "tags": p.tags_json or [], "topic_overlap": overlap,
                       "observed_views": p.observed_views,
                       "relative_views": round(lift, 2) if lift else None,
                       "score": round(score, 2), "language": p.language})
        authors[p.source_author] += 1
        kinds[p.hook_type] += 1
        if len(output) >= limit: break
    return output


def style_guidance(patterns: list[dict], *, intensity: int = 65) -> str:
    if not patterns:
        return "No sourced patterns yet. Write naturally; do not imply that competitor posts were analyzed."
    details = []
    for p in patterns:
        details.append(f"- Mechanic {p['hook_type']}: {p['structure']}; tone {p['tone']}; trigger {p['emotion']}; delivery: {', '.join(p['tags']) or 'natural'}. (research ID {p['source_post_id']}, no quotation)")
    return ("Editorial inspiration from analyzed public/consented research posts. These are ABSTRACT structures, not text to copy. "
            "Do not imitate named people, claim to be them, reproduce distinctive phrases, or fabricate anecdotes. "
            "Choose at most 2 distinct mechanisms per post; vary hooks between variants. "
            f"Intensity of bold/controversial delivery: {intensity}/100 (never misleading or abusive).\n" + "\n".join(details))
