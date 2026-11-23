"""Agent: Viral Pattern Detector."""
from __future__ import annotations

from .provider import ai_json
from .prompts import viral_prompt


async def analyze(text: str, metrics_context: str = "") -> dict:
    prompt, system = viral_prompt(text, metrics_context)
    return await ai_json(prompt, system)
