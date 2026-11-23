"""Agent: CTA Analyzer."""
from __future__ import annotations

from .provider import ai_json
from .prompts import cta_prompt


async def analyze(text: str) -> dict:
    prompt, system = cta_prompt(text)
    return await ai_json(prompt, system)
