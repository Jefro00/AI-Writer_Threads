"""Monitoring of the researcher's explicit list of interesting authors.

Two official modes:
- `/profile_posts?username=...` with `threads_profile_discovery` (no numeric ID
  required — this is the preferred path);
- `/{threads-user-id}/threads` for authors where we already have an ID.
"""
from __future__ import annotations

from datetime import datetime

import httpx

from app.config import settings

from .base import SourceAdapter, SourceResult, RawPost, RawProfile, request_with_retry


class AccountMonitorSource(SourceAdapter):
    name = "account_monitor"
    source_type = "monitor"

    def __init__(self, enabled: bool = True, config: dict | None = None) -> None:
        super().__init__(enabled, config)
        self.token = settings.threads_access_token
        self.base = settings.threads_api_base.rstrip("/")
        self.discovery_enabled = (
            settings.threads_profile_discovery_enabled
            or bool(self.config.get("profile_discovery_enabled"))
        )

    def is_enabled(self) -> bool:
        return self.enabled and bool(self.token)

    def _permission_error(self, response: httpx.Response, result: SourceResult, what: str) -> bool:
        if response.status_code < 400:
            return False
        body = response.text.lower()
        if "permission" in body or "scope" in body or "profile_discovery" in body:
            if "4279067" in response.text:
                result.skipped = (
                    "Meta requires App Review (Advanced Access) for "
                    "threads_profile_discovery. Standard access only allows "
                    "official Meta accounts. Submit the permission for review."
                )
            else:
                result.skipped = (
                    f"Meta did not grant threads_profile_discovery for {what}. "
                    "Re-issue the access token with this scope."
                )
            return True
        result.errors.append(f"Monitor {what}: HTTP {response.status_code} {response.text[:160]}")
        return True

    async def collect(self, params: dict) -> SourceResult:
        result = SourceResult()
        if not self.token:
            result.errors.append("THREADS_ACCESS_TOKEN not configured; account monitor disabled")
            return result

        # Both forms are accepted: {"username": id_or_None} and a plain list.
        raw_handles = params.get("handles") or {}
        if isinstance(raw_handles, list):
            handles: dict[str, str | None] = {str(u).lstrip("@"): None for u in raw_handles}
        else:
            handles = {str(u).lstrip("@"): (str(v) if v else None) for u, v in raw_handles.items()}
        extra_usernames = params.get("usernames") or []
        for username in extra_usernames:
            handles.setdefault(str(username).lstrip("@"), None)

        if not handles:
            result.skipped = (
                "No monitored authors. Add them in Data & Jobs (username is enough; "
                "a Threads user ID is optional when profile discovery is enabled)."
            )
            return result

        async with httpx.AsyncClient(timeout=40.0) as client:
            for username, user_id in handles.items():
                if user_id:
                    path = f"{self.base}/{user_id}/threads"
                    query = {
                        "fields": "id,text,timestamp,permalink,media_type",
                        "limit": int(params.get("limit", 25)),
                    }
                else:
                    if not self.discovery_enabled:
                        result.skipped = (
                            "Threads user IDs are missing. Add threads_profile_discovery "
                            "in Meta, re-issue the token and set "
                            "THREADS_PROFILE_DISCOVERY_ENABLED=true to poll by username."
                        )
                        continue
                    path = f"{self.base}/profile_posts"
                    query = {
                        "username": username,
                        "fields": "id,text,timestamp,permalink,media_type,username",
                        "limit": int(params.get("limit", 25)),
                    }
                query["access_token"] = self.token
                response = await request_with_retry(client, "GET", path, limiter=self.limiter, params=query)
                if self._permission_error(response, result, username):
                    continue
                if response.status_code >= 400:
                    result.errors.append(f"Monitor {username}: HTTP {response.status_code}")
                    continue
                try:
                    data = response.json()
                except ValueError:
                    result.errors.append(f"Monitor {username}: non-JSON response")
                    continue
                for item in data.get("data", []):
                    text = item.get("text") or ""
                    if not text.strip():
                        continue
                    ts = item.get("timestamp")
                    result.posts.append(
                        RawPost(
                            external_id=str(item.get("id")),
                            text=text,
                            author_username=username,
                            post_url=item.get("permalink"),
                            published_at=datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None,
                            content_type=item.get("media_type", "TEXT"),
                            raw=item,
                        )
                    )
                if self.discovery_enabled:
                    await self._enrich_profile(client, username, result)
        return result

    async def _enrich_profile(self, client: httpx.AsyncClient, username: str, result: SourceResult) -> None:
        """Public profile card: followers, bio, 7-day engagement (metadata only)."""
        response = await request_with_retry(
            client, "GET", f"{self.base}/profile_lookup",
            limiter=self.limiter,
            params={"access_token": self.token, "username": username},
        )
        if response.status_code >= 400:
            return  # enrichment is best-effort, never fatal
        try:
            data = response.json()
        except ValueError:
            return
        result.profiles.append(
            RawProfile(
                username=username,
                bio=data.get("biography"),
                followers_count=data.get("follower_count"),
                profile_url=f"https://www.threads.com/@{username}",
            )
        )
