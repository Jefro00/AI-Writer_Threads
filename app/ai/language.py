"""Language detection helper. AI result wins; offline guess is the fallback."""
from __future__ import annotations

from app.utils import guess_language


def resolve_language(detected: str | None, text: str) -> str:
    if detected and detected not in {"und", "auto", ""}:
        return detected[:20]
    return guess_language(text)
