"""Localized keyword expansion for multilingual research."""
from __future__ import annotations

# Equivalent phrases for cross-language search. Original post text is never
# translated or replaced; these terms are only used as search queries.
EQUIVALENTS: dict[str, list[str]] = {
    "ai tools": ["ai tools", "ai инструменты", "herramientas de ia", "ki tools", "outils ia"],
    "ai agents": ["ai agents", "ai агенты", "agentes de ia", "ki agenten"],
    "automation": ["automation", "автоматизация", "automatización", "automatisierung"],
    "solana": ["solana", "solana", "solana", "solana"],
    "defi": ["defi", "дефи", "defi", "defi"],
    "lead generation": ["lead generation", "генерация лидов", "generación de leads", "leadgenerierung"],
    "personal branding": ["personal branding", "личный бренд", "marca personal", "personal branding"],
    "building in public": ["building in public", "строим в публичном", "construir en público", "offen bauen"],
    "startup": ["startup", "стартап", "startup", "startup"],
    "free tool": ["free tool", "бесплатный инструмент", "herramienta gratuita", "kostenloses tool"],
}

NICHES = {
    "AI / SaaS": ["ai agents", "ai tools", "automation", "saas", "no-code", "productivity"],
    "Crypto / Web3": ["solana", "ethereum", "defi", "rwa", "nft", "trading", "crypto infrastructure"],
    "Marketing / Sales": ["growth hacking", "seo", "funnels", "lead generation", "copywriting", "personal branding"],
    "Business / Startups": ["indie hackers", "founders", "bootstrapping", "startups", "entrepreneurship", "product launches"],
}


def expand_keywords(keywords: list[str], languages: list[str] | None = None) -> list[str]:
    """Expand each keyword into its localized equivalents."""
    out: list[str] = []
    for kw in keywords:
        base = kw.strip().lower()
        variants = EQUIVALENTS.get(base, [kw])
        if languages:
            lang_index = {"en": 0, "ru": 1, "es": 2, "de": 3, "fr": 4}
            picked = []
            for lang in languages:
                idx = lang_index.get(lang)
                if idx is not None and idx < len(variants):
                    picked.append(variants[idx])
            variants = picked or [kw]
        for v in variants:
            if v and v not in out:
                out.append(v)
    return out
