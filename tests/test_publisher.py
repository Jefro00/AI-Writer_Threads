"""Auto-publish queue: approval gate, idempotency, missing token."""
from __future__ import annotations

import asyncio

from app.database.models import Post as WriterPost
from app.database.session import SessionLocal
from app.scheduler import run_auto_publish


def _make_post(text: str, status: str = "draft") -> int:
    with SessionLocal() as db:
        post = WriterPost(text=text, category="Crypto Discussion", language="ru", status=status)
        db.add(post)
        db.commit()
        return post.id


def test_auto_publish_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AUTO_PUBLISH_ENABLED", raising=False)
    result = asyncio.run(run_auto_publish())
    assert result["status"] == "disabled"


def test_auto_publish_requires_token(monkeypatch):
    monkeypatch.setenv("AUTO_PUBLISH_ENABLED", "true")
    monkeypatch.setenv("THREADS_ACCESS_TOKEN", "")
    result = asyncio.run(run_auto_publish())
    assert result["status"] == "skipped"
    assert "THREADS_ACCESS_TOKEN" in result["reason"]


def test_only_approved_posts_are_published(monkeypatch):
    import app.publisher as publisher

    draft_id = _make_post("Черновик без одобрения", "draft")
    approved_id = _make_post("Одобренный пост", "approved")

    monkeypatch.setenv("AUTO_PUBLISH_ENABLED", "true")
    monkeypatch.setenv("AUTO_PUBLISH_REQUIRE_APPROVAL", "true")
    monkeypatch.setenv("THREADS_ACCESS_TOKEN", "dummy-token")

    published: list[str] = []

    async def fake_publish(text: str):
        published.append(text)
        return publisher.PublishResult(threads_post_id=f"threads-{len(published)}")

    monkeypatch.setattr(publisher, "publish_text", fake_publish)
    result = asyncio.run(run_auto_publish())

    assert result["status"] == "ok"
    assert published == ["Одобренный пост"]
    with SessionLocal() as db:
        assert db.get(WriterPost, approved_id).status == "published"
        assert db.get(WriterPost, draft_id).status == "draft"


def test_bypass_approval_flag(monkeypatch):
    import app.publisher as publisher

    draft_id = _make_post("Авто-пост без одобрения", "pending_review")
    monkeypatch.setenv("AUTO_PUBLISH_ENABLED", "true")
    monkeypatch.setenv("AUTO_PUBLISH_REQUIRE_APPROVAL", "false")
    monkeypatch.setenv("THREADS_ACCESS_TOKEN", "dummy-token")

    async def fake_publish(text: str):
        return publisher.PublishResult(threads_post_id="threads-auto")

    monkeypatch.setattr(publisher, "publish_text", fake_publish)
    result = asyncio.run(run_auto_publish())
    assert result["status"] == "ok"
    with SessionLocal() as db:
        assert db.get(WriterPost, draft_id).status == "published"


def test_status_endpoint(client, auth):
    data = client.get("/api/research/autopublish", auth=auth).json()
    assert "enabled" in data
    assert "require_approval" in data
