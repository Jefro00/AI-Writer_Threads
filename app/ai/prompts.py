"""Versioned prompts. Each agent has a prompt version used for cache keys."""
from __future__ import annotations

PROMPT_VERSIONS: dict[str, str] = {
    "content_classifier": "v1.0",
    "strategy_analyzer": "v1.0",
    "cta_analyzer": "v1.0",
    "funnel_analyzer": "v1.0",
    "viral_detector": "v1.0",
    "competitor_analyzer": "v1.0",
    "insight_generator": "v1.0",
    "report_generator": "v1.0",
    "landing_analyzer": "v1.0",
}

NICHE_LIST = ["AI / SaaS", "Crypto / Web3", "Marketing / Sales", "Business / Startups", "Other"]
FORMAT_LIST = [
    "building_in_public", "educational", "personal_story", "direct_promotion",
    "native_promotion", "problem_solution", "list", "question", "controversy", "other",
]
MECHANICS_LIST = [
    "Storytelling", "Building in Public", "Social Proof", "Pain Point", "Free Value",
    "Product Demo", "Soft Selling", "Direct Selling", "Controversy", "Community Building",
    "Lead Magnet", "Launch Campaign",
]

RULES = """
CRITICAL RULES:
- Analyze only the supplied text. Never invent views, likes, sales, conversions, clicks or traffic.
- If a fact is not present in the text, return null or an empty list. Do not guess numbers.
- Preserve the original language. Do not translate the post.
- Return ONLY a single valid JSON object. No markdown, no explanation.
"""


def classifier_prompt(text: str, author_hint: str = "") -> tuple[str, str]:
    system = (
        "You are a precise content classifier for a marketing research engine. "
        + RULES
    )
    prompt = f"""Classify this Threads post.

Author context (may be empty): {author_hint}

POST TEXT:
\"\"\"{text}\"\"\"

Return JSON with keys:
- "niche": one of {NICHE_LIST}
- "subcategories": array of strings (multiple labels allowed)
- "language": ISO 639-1 code
- "format": one of {FORMAT_LIST}
- "tone": short string (e.g. casual, analytical, provocative)
- "intent": short string (e.g. product_awareness, education, community)
- "target_audience": array of strings
- "confidence": number 0..1
"""
    return prompt, system


def strategy_prompt(text: str) -> tuple[str, str]:
    system = "You are a marketing strategy analyst. " + RULES
    prompt = f"""Identify the marketing mechanics used in this Threads post.

POST TEXT:
\"\"\"{text}\"\"\"

Choose zero or more from: {MECHANICS_LIST}. You may add a short custom label if needed.
Return JSON:
- "mechanics": array of {{"name": string, "evidence": string, "confidence": number 0..1}}
- "primary_goal": string
- "confidence": number 0..1
"""
    return prompt, system


def cta_prompt(text: str) -> tuple[str, str]:
    system = "You are a CTA (call-to-action) detector. " + RULES
    prompt = f"""Find every call to action in this Threads post.

POST TEXT:
\"\"\"{text}\"\"\"

Return JSON:
- "ctas": array of objects with keys:
  "text" (exact CTA phrase from the post or null),
  "type" ("link_in_bio"|"comment"|"dm"|"join"|"try_free"|"signup"|"early_access"|"follow"|"reply"|"other"|null),
  "is_direct": boolean,
  "placement": string,
  "target_action": string,
  "commercial_intent": string ("none"|"low"|"medium"|"high"),
  "confidence": number 0..1
- "confidence": number 0..1
"""
    return prompt, system


def funnel_prompt(text: str, profile_bio: str = "", links: str = "") -> tuple[str, str]:
    system = "You are a funnel detective for organic growth research. " + RULES
    prompt = f"""Analyze the observable user journey in this Threads post.

POST TEXT:
\"\"\"{text}\"\"\"

AUTHOR BIO (public, may be empty): {profile_bio}
EXTERNAL LINKS FOUND (may be empty): {links}

Return JSON:
- "funnel_type": one of [Direct Website, Telegram, Instagram, Lead Magnet, SaaS, Newsletter, Community, DM Funnel, Affiliate, E-commerce, Unknown]
- "stages": array of objects {{"step_type": string, "description": string, "is_observed": boolean, "proof_level": "L1".."L7", "confidence": 0..1}}
- "product_mentions": array of strings
- "commercial_signals": array of strings
- "proof_level": highest observed level "L1".."L5" (never claim L6/L7 without analytics evidence)
- "confidence": number 0..1
Remember: finding a link or signup button is L3-L5 only, NOT a proven conversion.
"""
    return prompt, system


def viral_prompt(text: str, metrics_context: str = "") -> tuple[str, str]:
    system = "You are a viral pattern analyst. " + RULES
    prompt = f"""Describe the repeatable structural pattern of this successful post.

METRICS CONTEXT (author-supplied, do not alter): {metrics_context}

POST TEXT:
\"\"\"{text}\"\"\"

Return JSON:
- "pattern": short name
- "blocks": array of strings describing the sequence (hook, problem, story, result, question, CTA, etc.)
- "hooks": array of strings
- "confidence": number 0..1
"""
    return prompt, system


def landing_prompt(page_text: str) -> tuple[str, str]:
    system = "You are a landing-page analyst. " + RULES
    prompt = f"""Extract a product card from this public product page text.

PAGE TEXT (truncated):
\"\"\"{page_text[:6000]}\"\"\"

Return JSON:
- "name", "description", "target_audience" (array), "main_offer", "ctas" (array),
  "has_free_tier" (boolean), "pricing" (array of strings), "has_registration" (boolean),
  "has_demo" (boolean), "has_referral_program" (boolean), "community_links" (array),
  "advantages" (array), "confidence": number 0..1
If a field is not present, use null or empty list. Never invent prices.
"""
    return prompt, system
