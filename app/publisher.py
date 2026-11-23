"""Threads publishing helper shared by the manual endpoint and the scheduler."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
from fastapi import HTTPException

from app.config import settings


@dataclass
class PublishResult:
    threads_post_id: str
    url: str | None = None


class ThreadsPublishError(RuntimeError):
    pass


async def publish_text(text: str) -> PublishResult:
    """Create a Threads container and publish it. No DB writes here."""
    token = settings.threads_access_token
    if not token:
        raise ThreadsPublishError("THREADS_ACCESS_TOKEN is not configured")
    if not text or not text.strip():
        raise ThreadsPublishError("Post text is empty")

    base = settings.threads_api_base.rstrip("/")
    timeout = httpx.Timeout(45.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        create = await client.post(
            f"{base}/me/threads",
            params={"media_type": "TEXT", "text": text, "access_token": token},
        )
        if create.status_code >= 400:
            raise ThreadsPublishError(f"Threads container error HTTP {create.status_code}: {create.text[:300]}")
        creation_id = create.json().get("id")
        if not creation_id:
            raise ThreadsPublishError("Threads did not return a creation ID")

        # Meta can need a moment before the container is publishable.
        await asyncio.sleep(1)
        publish = await client.post(
            f"{base}/me/threads_publish",
            params={"creation_id": creation_id, "access_token": token},
        )
        if publish.status_code >= 400:
            raise ThreadsPublishError(f"Threads publish error HTTP {publish.status_code}: {publish.text[:300]}")
        published_id = publish.json().get("id")
        if not published_id:
            raise ThreadsPublishError("Threads did not return a published post ID")

    permalink = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0)) as client:
            info = await client.get(
                f"{base}/{published_id}",
                params={"fields": "permalink", "access_token": token},
            )
        if info.status_code == 200:
            permalink = info.json().get("permalink")
    except httpx.HTTPError:
        pass
    return PublishResult(threads_post_id=str(published_id), url=permalink)


def as_http_error(exc: ThreadsPublishError) -> HTTPException:
    return HTTPException(502, str(exc))
