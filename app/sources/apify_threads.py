"""Optional public Threads research via a third-party Apify Actor.

Separate from official Threads OAuth. Uses only public post data; never sends
Meta credentials. External scraping availability / terms may change. Runs are
user-triggered and limited in size; no automatic retries that incur new costs.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

import httpx

from app.config import settings
from .base import RawPost, RawProfile, SourceAdapter, SourceResult

ACTOR_ID = "agenttoolworks~threads-scraper"  # documented searchQueries/profiles contract
ENDPOINT = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"


def _value_int(value):
    if value is None or value == "":
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def transform_items(rows: list[dict], own_username: str = "") -> SourceResult:
    result = SourceResult()
    own = own_username.strip().lstrip("@").casefold()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("status") not in (None, "ok"):
            # Actor diagnostic rows are not posts
            continue
        if row.get("rowType") == "profile":
            handle = str(row.get("username") or "").strip().lstrip("@")
            if handle and handle.casefold() != own:
                result.profiles.append(RawProfile(
                    username=handle,
                    profile_url=row.get("url"),
                    bio=row.get("biography"),
                    followers_count=_value_int(row.get("followerCount")),
                ))
            continue
        if row.get("rowType") not in ("post", None):
            continue
        text = row.get("text")
        author = str(row.get("authorUsername") or "").strip().lstrip("@")
        if not isinstance(text, str) or not text.strip() or not author or author.casefold() == own:
            continue
        url = row.get("url")
        if url:
            parsed = urlparse(str(url))
            if parsed.scheme != "https" or parsed.hostname not in {"threads.com", "www.threads.com", "threads.net", "www.threads.net"}:
                url = None
        result.posts.append(RawPost(
            external_id=str(row.get("postId")) if row.get("postId") else None,
            author_username=author,
            text=text.strip(), post_url=url,
            published_at=_date(row.get("createdAt")),
            language=row.get("language"),
            content_type="TEXT", is_reply=bool(row.get("isReply")),
            views=None,  # Actor does not have public view counts
            likes=_value_int(row.get("likeCount")),
            replies=_value_int(row.get("replyCount")),
            reposts=_value_int(row.get("repostCount")),
            quotes=_value_int(row.get("quoteCount")),
            raw={"provider": "apify", "actor": ACTOR_ID, "source": row.get("source"), "sourceType": row.get("sourceType")},
        ))
    return result


class ApifyThreadsSource(SourceAdapter):
    name = "apify_threads"
    source_type = "third_party_api"

    def is_enabled(self) -> bool:
        return self.enabled and bool(settings.apify_token)

    async def collect(self, params: dict) -> SourceResult:
        result = SourceResult()
        token = settings.apify_token
        if not token:
            result.skipped = "APIFY_TOKEN отсутствует. Добавьте его в Render Environment."
            return result
        mode = params.get("mode", "search")
        max_items = min(settings.apify_max_items, max(1, int(params.get("limit") or 20)))
        if mode == "search":
            terms = params.get("keywords") or ([params["query"]] if params.get("query") else [])
            terms = [str(t).strip()[:200] for t in terms if str(t).strip()][:3]
            if not terms:
                result.skipped = "Не указаны ключевые слова"
                return result
            payload = {"searchQueries": terms, "maxItems": max_items}
        elif mode == "profiles":
            handles = [str(h).strip().lstrip("@") for h in params.get("handles", []) if str(h).strip()][:5]
            if not handles:
                result.skipped = "Не указаны аккаунты для мониторинга"
                return result
            payload = {"profiles": handles, "maxPostsPerProfile": min(20, max_items), "maxItems": max_items}
        else:
            result.errors.append("Unsupported Apify mode")
            return result
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(115.0, connect=10.0)) as client:
                response = await client.post(
                    ENDPOINT,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json=payload,
                    params={"timeout": 100},
                )
            if response.status_code != 200:
                result.errors.append(f"Apify HTTP {response.status_code}; проверьте лимит, токен и статус Actor")
                return result
            data = response.json()
            if not isinstance(data, list):
                result.errors.append("Apify вернул не список публикаций. Проверьте журнал Apify")
                return result
            return transform_items(data, own_username=settings.threads_own_username)
        except (httpx.HTTPError, ValueError) as exc:
            result.errors.append(f"Apify request failed: {type(exc).__name__} (see Apify Console for run status)")
            return result
