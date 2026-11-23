"""Meta Content Library adapter (optional research-only source).

The Content Library is a restricted research product, not a general commercial
API. Threads posts appear there for public profiles with 100+ followers; CSV
export is not supported. Therefore this source is OPTIONAL and disabled unless
META_CONTENT_LIBRARY_TOKEN is configured. It never blocks other sources.
"""
from __future__ import annotations

from datetime import datetime

import httpx

from app.config import settings

from .base import SourceAdapter, SourceResult, RawPost, request_with_retry


class ContentLibrarySource(SourceAdapter):
    name = "content_library"
    source_type = "research"

    def __init__(self, enabled: bool = True, config: dict | None = None) -> None:
        super().__init__(enabled, config)
        self.token = settings.content_library_token
        # Meta Content Library Graph API base; overridable via config.
        self.base = self.config.get("api_base", "https://graph.facebook.com/v20.0")

    def is_enabled(self) -> bool:
        return self.enabled and bool(self.token)

    async def collect(self, params: dict) -> SourceResult:
        result = SourceResult()
        if not self.token:
            result.errors.append("META_CONTENT_LIBRARY_TOKEN not configured; optional research source disabled")
            return result

        keywords = params.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        languages = params.get("languages") or []
        date_from = params.get("date_from")
        date_to = params.get("date_to")

        async with httpx.AsyncClient(timeout=50.0) as client:
            for keyword in keywords:
                query: dict = {
                    "access_token": self.token,
                    "q": keyword,
                    "type": "threads",
                    "limit": int(params.get("limit", 50)),
                }
                if languages:
                    query["language"] = ",".join(languages)
                if date_from:
                    query["since"] = date_from
                if date_to:
                    query["until"] = date_to
                endpoint = self.config.get("search_endpoint", f"{self.base}/content_library/search")
                try:
                    response = await request_with_retry(client, "GET", endpoint, limiter=self.limiter, params=query)
                except httpx.RequestError as exc:
                    result.errors.append(f"Content Library connection error: {type(exc).__name__}")
                    continue
                if response.status_code >= 400:
                    result.errors.append(f"Content Library HTTP {response.status_code}: {response.text[:200]}")
                    continue
                try:
                    data = response.json()
                except ValueError:
                    result.errors.append("Content Library returned non-JSON")
                    continue
                for item in data.get("data", []):
                    text = item.get("message") or item.get("text") or ""
                    if not str(text).strip():
                        continue
                    ts = item.get("created_time") or item.get("timestamp")
                    result.posts.append(
                        RawPost(
                            external_id=str(item.get("id")) if item.get("id") else None,
                            text=text,
                            author_username=item.get("author") or item.get("username"),
                            post_url=item.get("permalink_url"),
                            published_at=datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None,
                            language=item.get("language"),
                            content_type=item.get("type", "threads"),
                            views=item.get("views"),
                            likes=item.get("likes"),
                            replies=item.get("replies"),
                            reposts=item.get("shares"),
                            quotes=item.get("quotes"),
                            raw=item,
                        )
                    )
        return result
