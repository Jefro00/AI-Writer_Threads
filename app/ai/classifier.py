"""Agent: Content Classifier."""
from __future__ import annotations

from .provider import ai_json
from .prompts import classifier_prompt


async def classify(text: str, author_hint: str = "") -> dict:
    prompt, system = classifier_prompt(text, author_hint)
    return await ai_json(prompt, system)
