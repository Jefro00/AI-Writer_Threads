"""Agent: Marketing Strategy Analyzer."""
from __future__ import annotations

from .provider import ai_json
from .prompts import strategy_prompt


async def analyze(text: str) -> dict:
    prompt, system = strategy_prompt(text)
    return await ai_json(prompt, system)
