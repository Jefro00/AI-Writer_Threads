"""Generate and validate a batch of hook-first posts in ONE AI request.

No affiliate promise is inferred. The offer benefits are suggestions, not
verified facts; without a source the model is instructed not to assert them.
"""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import HTTPException

from app.marketing.hooks import (HOOK_TYPES, MAX_CHARS, PROMPT_VERSION,
                                 clean_text, editorial_score, unique_variants)
from app.writer_service import complete_prompt

DISCLOSURES = {
    "ru": "Партнёрская ссылка. Могу получить комиссию.",
    "en": "Referral link. I may earn a commission.",
}
URL_RE = re.compile(r"https?://[^\s<>\"'()]+")


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I).rsplit("```", 1)[0].strip()
    try:
        obj = json.loads(text)
    except ValueError:
        # Handles a model adding a short explanation before/after JSON.
        try:
            obj = json.loads(text[text.index("{"):text.rindex("}") + 1])
        except (ValueError, IndexError) as exc:
            raise HTTPException(502, "AI вернул не JSON. Повтори генерацию или смени модель.") from exc
    if not isinstance(obj, dict) or not isinstance(obj.get("variants"), list):
        raise HTTPException(502, "AI не вернул список вариантов. Повтори запрос.")
    return obj


def _finish_text(text: str, *, language: str, promotion_style: str,
                 goal: str, link: str | None, offer_name: str | None = None) -> str:
    body = clean_text(text)
    if not body:
        raise ValueError("empty post")
    # The application, not the LLM, owns all outgoing links and disclosures.
    body = URL_RE.sub("", body).strip()
    disclosure = DISCLOSURES.get(language[:2], DISCLOSURES["en"])
    for marker in DISCLOSURES.values():
        body = body.replace(marker, "").strip()
    # Remove common model-generated duplicate disclosure.
    body = re.sub(r"(?im)^\s*(?:партн[её]рская ссылка|реклама|referral link|affiliate link)\s*[:.]?\s*$", "", body).strip()
    show_link = bool(link) and promotion_style in {"soft", "direct"} and goal in {"clicks", "signup"}
    # A naked referral URL is not a useful or honest call to action.
    if show_link and offer_name and offer_name.casefold() not in body.casefold():
        bridge = (f"Можно изучить {offer_name} как один из инструментов."
                  if language.startswith("ru") else f"{offer_name} is one option to explore.")
        body += "\n\n" + bridge
    tail = ("\n\n" + link + "\n" + disclosure) if show_link else ("\n\n" + disclosure if promotion_style in {"soft", "direct"} and link and ("fomo" in body.lower()) else "")
    room = MAX_CHARS - len(tail)
    if room < 45:
        raise ValueError("referral URL is too long")
    if len(body) > room:
        body = body[:room].rsplit(" ", 1)[0].rstrip(" ,.!?;:") + "…"
    if not body:
        raise ValueError("empty post")
    return body + tail


def build_growth_prompt(*, topic: str, category: str, language: str,
                        goal: str, hook_type: str, promotion_style: str,
                        offer: dict | None, link: str | None,
                        audience: str, count: int, feedback: str = "") -> str:
    lang = "Russian" if language.startswith("ru") else "English" if language.startswith("en") else language
    offer_text = "No affiliate offer." if not offer else (
        f"Brand: {offer['name']}. Description: {offer['description']}. "
        f"Audience: {offer['target_audience']}. "
        "These are unverified promotional notes; NEVER assert specific discounts, "
        "features, returns, earnings, prices or performance without reliable evidence. "
        f"Approved outgoing link: {link or 'none'}."
    )
    return f"""You are the editor of a real Russian-language crypto/Web3 Threads account JefroCrypto.
Produce ORIGINAL short natural social posts, with hard-hitting and DIFFERENT opening hooks.
Topic: {topic}
Category: {category}
Write in {lang}. Russian is conversational, lively, direct, without corporate copywriting, awkward Anglicisms, and long em dashes. No made-up first-person experience, unsourced claims, invented statistics, promises of profit, price targets, FOMO pressure or empty clickbait. No fake urgency.
Target audience: {audience}. Objective: {goal}.
Hook requested: {hook_type}; use 5 genuinely different hooks if auto (contrarian, curiosity, pain point, comparison, debate, story).
Promotion: {promotion_style}. If none: NO brand mention. Soft: natural relevant bridge, not a sales pitch. Direct: explain relevance without aggressive selling. For reach/discussion, don't add a link. For clicks/signup, offer must be truly relevant; the application adds the link and disclosure itself, so DO NOT output any URLs or affiliate disclosure.
{offer_text}
The first sentence must be specific and compelling; rest of the post must deliver. Avoid generic "А вы знали", "В мире криптовалют", "Друзья".
Do not copy any example or existing competitor post. Keep EACH full post under 350 characters to leave room for link + disclosure.
Feedback from actual data (may be empty, only as hypothesis): {feedback or 'No reliable previous results yet.'}
Return strict valid JSON (no markdown) with exactly this schema:
{{"hooks":[{{"type":"curiosity","text":"short opening sentence"}}],"variants":[{{"hook_type":"curiosity","text":"full post without URL"}}]}}
Provide 5 hooks, and {count} fully written post variants with DISTINCT hooks, ready for Threads. No labels or metadata inside posts. No explanations."""


async def generate_growth_variants(*, topic: str, category: str, language: str,
                                   goal: str, hook_type: str, promotion_style: str,
                                   offer: dict | None, link: str | None,
                                   audience: str, count: int, feedback: str = "") -> dict:
    prompt = build_growth_prompt(topic=topic, category=category, language=language, goal=goal,
                                hook_type=hook_type, promotion_style=promotion_style,
                                offer=offer, link=link, audience=audience, count=count, feedback=feedback)
    raw, model = await complete_prompt(prompt, token_multiplier=2, json_mode=True)
    obj = _parse_json(raw)
    hooks = []
    for row in obj.get("hooks", [])[:10]:
        if isinstance(row, dict) and isinstance(row.get("text"), str):
            hooks.append({"hook_type": str(row.get("type", "auto"))[:40], "text": clean_text(row["text"])[:160]})
    variants = []
    for row in obj["variants"][:8]:
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            continue
        kind = str(row.get("hook_type") or hook_type).lower()
        if kind not in HOOK_TYPES:
            kind = "auto"
        if hook_type != "auto" and kind != hook_type:
            kind = hook_type
        try:
            text = _finish_text(row["text"], language=language, promotion_style=promotion_style,
                                goal=goal, link=link, offer_name=(offer["name"] if offer else None))
        except ValueError:
            continue
        if 1 <= len(text) <= MAX_CHARS:
            variants.append({"text": text, "hook_type": kind,
                             "score": editorial_score(text, kind)})
    result = unique_variants(variants, count)
    if len(result) < count:
        raise HTTPException(502, f"AI подготовил только {len(result)} разных вариантов из {count}. Попробуй ещё раз.")
    return {"variants": result, "hooks": hooks, "prompt_version": PROMPT_VERSION, "ai_model": model}
