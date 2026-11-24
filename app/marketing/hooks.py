"""Editorial heuristics. Scores are not CTR forecasts or measured lift."""
from __future__ import annotations

import re

HOOK_TYPES = {"auto", "contrarian", "curiosity", "pain_point", "comparison", "debate", "story"}
GOALS = {"reach", "discussion", "clicks", "signup"}
PROMO_STYLES = {"none", "soft", "direct"}
PROMPT_VERSION = "growth-v2-style"
MAX_CHARS = 500  # Threads text-only post limit, checked again before publishing.


def clean_text(raw: str) -> str:
    text = raw.strip().strip('`').strip()
    # Remove an accidental leading 'Post 1:' label or model quotation marks.
    text = re.sub(r"^(?:Пост|Вариант|Post|Variant)\s*\d+\s*[:.)-]\s*", "", text, flags=re.I)
    return text.strip().strip('"“”«»').strip()


def editorial_score(text: str, hook_type: str = "auto") -> float:
    """Simple, transparent editorial checklist. NOT predicted performance."""
    value = clean_text(text)
    if not value:
        return 0.0
    first = value.splitlines()[0].strip()
    score = 0.0
    # hook: up to 30
    score += 12 if 15 <= len(first) <= 110 else 4
    score += 8 if ("?" in first or ":" in first or len(first.split()) <= 13) else 3
    score += 10 if first and not first.lower().startswith(("привет", "сегодня поговорим", "всем привет", "hello everyone")) else 0
    # utility / readability: up to 25
    score += 13 if 120 <= len(value) <= MAX_CHARS else 6
    score += 12 if "\n" in value else 5
    # curiosity: up to 20
    score += 10 if hook_type in HOOK_TYPES - {"auto"} else 4
    score += 10 if "?" in value or "но " in value.lower() or "but " in value.lower() else 5
    # naturalness: up to 15
    score += 9 if len(re.findall(r"[🚀🔥💰💸❗!]", value)) <= 2 else 2
    score += 6 if not re.search(r"(100x|гарантир|без риска|guaranteed profit)", value, re.I) else 0
    # CTA / intent: up to 10
    score += 10 if "?" in value or "https://" in value else 5
    return round(min(100.0, score), 1)


def unique_variants(variants: list[dict], count: int) -> list[dict]:
    """Prefer distinct hooks, then editorial scores; no false prediction of clicks."""
    ranked = sorted(variants, key=lambda x: -float(x.get("score", 0)))
    selected: list[dict] = []
    seen_first: set[str] = set()
    seen_types: set[str] = set()
    for row in ranked:
        first = row["text"].splitlines()[0].strip().lower()
        if first in seen_first or row.get("hook_type") in seen_types:
            continue
        selected.append(row)
        seen_first.add(first)
        seen_types.add(row.get("hook_type"))
        if len(selected) == count:
            return selected
    for row in ranked:
        first = row["text"].splitlines()[0].strip().lower()
        if first not in seen_first:
            selected.append(row)
            seen_first.add(first)
        if len(selected) == count:
            return selected
    return selected
