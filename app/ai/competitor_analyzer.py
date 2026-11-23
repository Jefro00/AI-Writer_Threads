"""Agent: Competitor Intelligence.

Works on aggregated author statistics assembled by the analytics layer, not on
a single post. Produces a structured author profile.
"""
from __future__ import annotations

from .provider import ai_json, AIError

SYSTEM = (
    "You are a competitive marketing analyst. Use only the supplied statistics. "
    "Never invent metrics, sales or conversions. Return one JSON object."
)


async def analyze_profile(profile_data: dict) -> dict:
    prompt = f"""Build a marketing intelligence profile from these OBSERVED statistics.

{profile_data}

Return JSON:
- "summary": string
- "posting_frequency": string
- "successful_formats": array of strings
- "topics": array of strings
- "advertised_products": array of strings
- "cta_patterns": array of strings
- "strategy_changes": array of strings (only if history shows change)
- "confidence": number 0..1
"""
    try:
        return await ai_json(prompt, SYSTEM)
    except AIError:
        return {"summary": "AI unavailable", "confidence": 0.0}
