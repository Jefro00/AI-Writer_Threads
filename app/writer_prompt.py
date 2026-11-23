"""Prompt builder for the existing Writer.

Russian is now the default language. Other languages remain supported.
"""
from __future__ import annotations

LANGUAGES = {
    "en": ("English", "Sound like a thoughtful crypto-native person, not a marketing bot."),
    "ru": ("Russian", "Пиши живым языком крипто-исследователя, без канцелярита и рекламных штампов."),
    "es": ("Spanish", "Escribe como una persona cripto-nativa reflexiva, sin lenguaje corporativo."),
    "de": ("German", "Schreibe wie eine nachdenkliche Crypto-Native-Person, ohne Konzernsprache."),
    "fr": ("French", "Écris comme une personne crypto-native réfléchie, sans langage corporate."),
    "tr": ("Turkish", "Düşünceli bir kripto yerlisinin ses tonuyla yaz, kurumsal dil kullanma."),
}


def language_name(language: str | None) -> str:
    code = (language or "ru").strip().lower()[:2]
    return LANGUAGES.get(code, LANGUAGES["en"])[0]


def build_writer_prompt(
    topic: str,
    category: str,
    tone: str,
    language: str = "ru",
    structure: list[str] | None = None,
    examples: list[dict] | None = None,
    cta: str | None = None,
    style_limits: str | None = None,
    post_format: str | None = None,
) -> str:
    code = (language or "ru").strip().lower()[:2]
    name, voice_hint = LANGUAGES.get(code, (language or "English", ""))
    parts = [
        "You are the editorial writer for JefroCrypto, a real crypto/Web3 account on Threads.",
        "",
        f"Write ONE original Threads post in {name} about: {topic}",
        f"Category: {category}",
        f"Voice: {tone}.",
        voice_hint,
        "Open with a specific, non-generic hook that earns attention; follow with useful context. "
        "Use natural short sentences. No corporate language, fake personal claims, "
        "guaranteed returns, fabricated statistics, price predictions, or unsupported "
        "claims. Avoid engagement bait and repetitive hooks. Keep it under 450 characters. "
        "Mention FOMO or the referral link only if directly relevant; do not force promotion.",
        "Output only the post text, no quotation marks or explanation.",
    ]
    if structure:
        parts.append("Follow this structure (do not copy any source post verbatim): " + " → ".join(structure))
    if examples:
        parts.append(
            "Use these researched examples only as inspiration for a marketing pattern, "
            "never copy their wording: " + " | ".join(str(e)[:200] for e in examples[:3])
        )
    if cta:
        parts.append(f"Include a call to action of this type: {cta}")
    if post_format:
        parts.append(f"Requested format: {post_format}")
    if style_limits:
        parts.append(f"Additional style constraints: {style_limits}")
    return "\n".join(p for p in parts if p)
