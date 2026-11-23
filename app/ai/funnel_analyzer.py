"""Agent: Funnel Detective (plus public landing-page card extraction)."""
from __future__ import annotations

import re

import httpx

from app.config import settings
from app.utils import is_safe_url

from .provider import AIError, ai_json
from .prompts import funnel_prompt, landing_prompt


async def analyze(text: str, profile_bio: str = "", links: str = "") -> dict:
    prompt, system = funnel_prompt(text, profile_bio, links)
    return await ai_json(prompt, system)


def _extract_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = html.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", html).strip()


async def analyze_landing(url: str) -> dict:
    """Fetch a PUBLIC product page (safely) and build a product card.

    Refuses private/unsafe URLs and never executes JavaScript or downloads
    files. On network/parse failure returns an empty card with an error note.
    """
    if not is_safe_url(url):
        return {"error": "unsafe_url"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0), follow_redirects=False) as client:
            response = await client.get(url, headers={"User-Agent": "JefroCryptoResearch/1.0 (+public pages only)"})
            # Only follow a single safe redirect manually.
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if location and is_safe_url(location):
                    response = await client.get(location)
            if response.status_code >= 400:
                return {"error": f"http_{response.status_code}"}
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type:
                return {"error": "not_html"}
            page_text = _extract_text(response.text)
    except httpx.HTTPError:
        return {"error": "fetch_failed"}

    prompt, system = landing_prompt(page_text)
    try:
        return await ai_json(prompt, system)
    except AIError:
        return {"error": "ai_unavailable", "page_text_excerpt": page_text[:500]}
