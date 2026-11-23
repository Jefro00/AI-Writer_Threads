"""Source adapter contract.

Every source is independent and can be disabled without breaking the system.
Adapters return plain ``RawPost`` records; the normalizer converts them to ORM.
"""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx


@dataclass
class RawPost:
    external_id: str | None
    text: str
    author_username: str | None = None
    post_url: str | None = None
    published_at: datetime | None = None
    language: str | None = None
    content_type: str | None = "TEXT"
    is_reply: bool = False
    is_quote: bool = False
    views: int | None = None
    likes: int | None = None
    replies: int | None = None
    reposts: int | None = None
    quotes: int | None = None
    author_followers: int | None = None
    author_bio: str | None = None
    comments: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class RawProfile:
    username: str
    profile_url: str | None = None
    bio: str | None = None
    followers_count: int | None = None
    language: str | None = None
    country: str | None = None
    niches: list[str] = field(default_factory=list)
    advertised_products: list[str] = field(default_factory=list)


@dataclass
class SourceResult:
    posts: list[RawPost] = field(default_factory=list)
    profiles: list[RawProfile] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    insights: dict = field(default_factory=dict)
    links: list[dict] = field(default_factory=list)
    # Set when a source is legitimately unavailable (no credentials, no
    # authorized endpoint, nothing to monitor). Not an error.
    skipped: str | None = None

    @property
    def found(self) -> int:
        return len(self.posts)


class RateLimiter:
    """Simple token-bucket-ish limiter: no more than N calls per interval."""

    def __init__(self, max_calls: int = 20, per_seconds: float = 60.0) -> None:
        self.max_calls = max(1, max_calls)
        self.per_seconds = max(0.1, per_seconds)
        self._calls: list[float] = []

    async def wait(self) -> None:
        now = time.monotonic()
        self._calls = [t for t in self._calls if now - t < self.per_seconds]
        if len(self._calls) >= self.max_calls:
            sleep_for = self.per_seconds - (now - self._calls[0]) + 0.05
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            now = time.monotonic()
            self._calls = [t for t in self._calls if now - t < self.per_seconds]
        self._calls.append(time.monotonic())


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    limiter: RateLimiter | None = None,
    attempts: int = 3,
    **kwargs: Any,
) -> httpx.Response:
    """Perform an HTTP request with rate limiting and retry on transient errors."""
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        if limiter:
            await limiter.wait()
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < attempts - 1:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
                await asyncio.sleep(min(delay, 30))
                continue
            return response
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            last_error = exc
            if attempt < attempts - 1:
                await asyncio.sleep(2 ** attempt)
    if last_error:
        raise last_error
    raise RuntimeError("request_with_retry failed without a response")


class SourceAdapter(ABC):
    name: str = "base"
    source_type: str = "base"

    def __init__(self, enabled: bool = True, config: dict | None = None) -> None:
        self.enabled = enabled
        self.config = config or {}
        self.limiter = RateLimiter(
            max_calls=int(self.config.get("rate_limit_calls", 20)),
            per_seconds=float(self.config.get("rate_limit_seconds", 60)),
        )

    def is_enabled(self) -> bool:
        return self.enabled

    @abstractmethod
    async def collect(self, params: dict) -> SourceResult:
        """Collect data. Must never raise for expected cases; put errors in SourceResult.errors."""
        raise NotImplementedError
