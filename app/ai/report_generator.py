"""Agent: Research Report Generator (narrative part of a report)."""
from __future__ import annotations

from .provider import ai_json, AIError

SYSTEM = (
    "You are a research report writer. Use ONLY the supplied structured facts. "
    "Never invent numbers, sources, conversions or sales. Cite post ids when given. "
    "Explicitly mention data limitations. Return one JSON object."
)


async def generate(facts: dict) -> dict:
    prompt = f"""Write a concise research report from these facts.

FACTS:
{facts}

Return JSON:
- "patterns": array of strings
- "examples": array of {{"post_id": number, "why": string}}
- "format_comparison": array of strings
- "mechanics": array of strings
- "funnel_examples": array of strings
- "limitations": array of strings
- "recommendations": array of strings
- "confidence": number 0..1
"""
    try:
        return await ai_json(prompt, SYSTEM)
    except AIError:
        return {"patterns": [], "limitations": ["AI unavailable"], "confidence": 0.0}
