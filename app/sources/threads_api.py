"""Official Threads API adapter.

DESIGN NOTE: no scraping, no auth bypass, no CAPTCHA workarounds. If the token
is missing or a search endpoint is unavailable, the adapter reports the problem
in ``SourceResult.errors`` instead of fabricating data.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.config import settings
from app.utils import is_safe_url

from .base import SourceAdapter, SourceResult, RawPost, request_with_retry


class ThreadsApiSource(SourceAdapter):
    name = "threads_api"
    source_type = "api"

    def __init__(self, enabled: bool = True, config: dict | None = None) -> None:
        super().__init__(enabled, config)
        self.token = settings.threads_access_token
        self.base = settings.threads_api_base.rstrip("/")

    def is_enabled(self) -> bool:
        # Never claim to be connected without a token.
        return self.enabled and bool(self.token)

    async def collect(self, params: dict) -> SourceResult:
        result = SourceResult()
        if not self.token:
            result.errors.append("THREADS_ACCESS_TOKEN is not configured; source disabled")
            return result

        mode = params.get("mode", "profile")
        timeout = httpx.Timeout(40.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if mode == "profile":
                result.posts.extend(await self._own_posts(client, params, result))
            elif mode == "search":
                result.posts.extend(await self._keyword_search(client, params, result))
            elif mode == "insights":
                await self._insights(client, params, result)
            else:
                result.errors.append(f"Unknown Threads API mode: {mode}")
        return result

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict, result: SourceResult) -> dict:
        query = {"access_token": self.token, **params}
        response = await request_with_retry(client, "GET", f"{self.base}{path}", limiter=self.limiter, params=query)
        if response.status_code >= 400:
            result.errors.append(f"Threads API {path} HTTP {response.status_code}: {response.text[:200]}")
            return {}
        try:
            return response.json()
        except ValueError:
            result.errors.append(f"Threads API {path} returned non-JSON")
            return {}

    async def _own_posts(self, client: httpx.AsyncClient, params: dict, result: SourceResult) -> list[RawPost]:
        data = await self._get(client, "/me/threads", {"limit": int(params.get("limit", 25))}, result)
        posts: list[RawPost] = []
        for item in data.get("data", []):
            if item.get("media_type") not in (None, "TEXT"):
                continue
            text = item.get("text") or ""
            if not text.strip():
                continue  # media-only items have no post text to research
            permalink = item.get("permalink")
            if permalink and not is_safe_url(permalink):
                permalink = None
            ts = item.get("timestamp")
            posts.append(
                RawPost(
                    external_id=str(item.get("id")),
                    text=text,
                    post_url=permalink,
                    published_at=datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None,
                    content_type=item.get("media_type", "TEXT"),
                    raw=item,
                )
            )
        return posts

    async def _keyword_search(self, client: httpx.AsyncClient, params: dict, result: SourceResult) -> list[RawPost]:
        """Meta's official GET /keyword_search endpoint.

        Requires the `threads_keyword_search` permission approved by Meta.
        Without Advanced Access Meta can return only the authenticated user's
        posts with HTTP 200. In competitor mode we therefore verify the user's
        handle and refuse to count such results as competitor discoveries.
        """
        search_path = self.config.get("keyword_search_path") or "/keyword_search"
        enabled = (
            self.config.get("keyword_search_enabled")
            or settings.threads_keyword_search_enabled
        )
        if not enabled:
            result.skipped = (
                "Keyword search requires Meta's threads_keyword_search permission. "
                "Set THREADS_KEYWORD_SEARCH_ENABLED=true after your app is approved "
                "(or keyword_search_enabled=true in the source config)."
            )
            return []

        q = params.get("query") or params.get("keyword") or ""
        if not q:
            result.skipped = "No keyword/query supplied for search"
            return []
        query: dict = {
            "q": q,
            "search_type": params.get("search_type", "TOP"),
            "search_mode": params.get("search_mode", "KEYWORD"),
            "limit": min(100, max(1, int(params.get("limit", 25)))),
            "fields": "id,text,media_type,permalink,timestamp,username,has_replies,is_quote_post,is_reply",
        }
        if params.get("media_type"):
            query["media_type"] = params["media_type"]
        if params.get("since"):
            query["since"] = params["since"]
        if params.get("until"):
            query["until"] = params["until"]
        if params.get("author_username"):
            query["author_username"] = params["author_username"]

        data = await self._get(client, search_path, query, result)
        error_text = " ".join(result.errors).lower()
        if any(token in error_text for token in ("permission", "scope", "(#200)", "unsupported request", "4279067")):
            if "4279067" in error_text:
                result.skipped = (
                    "Meta requires App Review (Advanced Access) for public "
                    "threads_keyword_search. Standard access searches only "
                    "the authenticated user's own posts. Submit for review."
                )
            else:
                result.skipped = (
                    "Meta did not grant threads_keyword_search for this token. "
                    "Re-issue the access token with this scope."
                )
            result.errors.clear()
            return []

        posts: list[RawPost] = []
        for item in data.get("data", []):
            text = item.get("text") or ""
            if not text.strip():
                continue
            ts = item.get("timestamp")
            posts.append(
                RawPost(
                    external_id=str(item.get("id")),
                    text=text,
                    author_username=(item.get("username") or "").lstrip("@") or None,
                    post_url=item.get("permalink"),
                    published_at=datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None,
                    content_type=item.get("media_type", "TEXT"),
                    is_reply=bool(item.get("is_reply")),
                    is_quote=bool(item.get("is_quote_post")),
                    raw=item,
                )
            )
        if params.get("external_only", True) and posts:
            own = await self._resolve_own_username(client)
            if not own:
                result.skipped = (
                    "Нельзя подтвердить, что найдены посты других авторов: "
                    "не удалось определить подключённый Threads-аккаунт. "
                    "Укажи THREADS_OWN_USERNAME в .env и повтори поиск."
                )
                return []
            external = [
                p for p in posts
                if p.author_username and p.author_username.lower().lstrip("@") != own
            ]
            if not external:
                result.skipped = (
                    f"Поиск вернул только публикации @{own}. "
                    "Для поиска чужих постов требуется одобрение Meta App Review "
                    "(Advanced Access) для threads_keyword_search. "
                    "Флаг THREADS_KEYWORD_SEARCH_ENABLED=true сам по себе прав не даёт."
                )
                return []
            return external
        return posts

    async def _resolve_own_username(self, client: httpx.AsyncClient) -> str:
        """Find the authorized account; never guess an author from search data."""
        configured = settings.threads_own_username
        if configured:
            return configured
        if hasattr(self, "_own_username_cache"):
            return self._own_username_cache
        probe = SourceResult()
        try:
            data = await self._get(client, "/me", {"fields": "username"}, probe)
            own = str(data.get("username") or "").strip().lstrip("@").lower()
        except (httpx.HTTPError, ValueError, TypeError):
            own = ""
        self._own_username_cache = own
        return own

    async def _insights(self, client: httpx.AsyncClient, params: dict, result: SourceResult) -> None:
        """Fetch own-profile Insights metrics (views, clicks, replies, etc.).

        Stored on the result as raw data in errors? No - returned through a
        dedicated attribute for the collector to persist on our own posts.
        """
        metric = params.get("metric", "views,likes,replies,reposts,quotes")
        since = params.get("since")
        until = params.get("until")
        extra: dict[str, Any] = {"metric": metric}
        if since:
            extra["since"] = since
        if until:
            extra["until"] = until
        data = await self._get(client, "/me/threads_insights", extra, result)
        result.insights = data
