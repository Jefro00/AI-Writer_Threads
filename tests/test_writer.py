"""Russian/English Writer prompt + Research → Writer brief language."""
from __future__ import annotations

from app.writer_prompt import build_writer_prompt


def test_prompt_russian_is_default():
    prompt = build_writer_prompt("Solana", "Crypto Discussion", "natural")
    assert "in Russian" in prompt
    assert "in English" not in prompt


def test_prompt_russian():
    prompt = build_writer_prompt("Солана", "Crypto Discussion", "natural", language="ru")
    assert "in Russian" in prompt
    assert "крипто-исследователя" in prompt


def test_prompt_carries_brief_fields():
    prompt = build_writer_prompt(
        "AI агенты", "AI / SaaS", "casual", language="ru",
        structure=["Проблема", "Личная история", "Решение"],
        cta="Try it for free", style_limits="без гарантий доходности",
        post_format="thread",
    )
    assert "Проблема → Личная история → Решение" in prompt
    assert "Try it for free" in prompt
    assert "без гарантий доходности" in prompt
    assert "Requested format: thread" in prompt


def test_post_language_stored(client, auth):
    from app.database.models import Post as WriterPost
    from app.database.session import SessionLocal

    with SessionLocal() as db:
        post = WriterPost(text="тест", category="Crypto Discussion", language="ru", status="draft")
        db.add(post); db.commit()
        pid = post.id
    rows = client.get("/api/posts", auth=auth).json()
    assert any(r["id"] == pid and r["language"] == "ru" for r in rows)


def test_reasoning_truncation_is_detected():
    from app.writer_service import _truncated_by_reasoning

    usage = {"completion_tokens_details": {"reasoning_tokens": 512}}
    assert _truncated_by_reasoning({"finish_reason": "length"}, usage) is True
    assert _truncated_by_reasoning({"finish_reason": "stop"}, usage) is False
    assert _truncated_by_reasoning({"finish_reason": "length"}, {}) is False


def test_writer_retries_when_reasoning_ate_the_budget(monkeypatch):
    import asyncio
    import os

    import app.writer_service as svc

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openrouter/free")

    calls: list[int] = []

    class FakeResponse:
        status_code = 200

        def __init__(self, reasoning: bool):
            self._reasoning = reasoning

        def json(self):
            if self._reasoning:
                return {
                    "choices": [{"finish_reason": "length", "message": {"content": None}}],
                    "usage": {"completion_tokens_details": {"reasoning_tokens": 1600}},
                }
            return {
                "choices": [{"finish_reason": "stop", "message": {"content": "Готовый пост"}}],
                "usage": {},
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            calls.append(kwargs["json"]["max_tokens"])
            return FakeResponse(reasoning=len(calls) == 1)

    monkeypatch.setattr(svc.httpx, "AsyncClient", lambda *a, **kw: FakeClient())
    text = asyncio.run(svc.generate_text(topic="тест", language="ru"))
    assert text == "Готовый пост"
    assert calls == [svc.MAX_TOKENS, svc.RETRY_MAX_TOKENS]


def test_brief_language(client, auth):
    response = client.post("/api/research/briefs", auth=auth, json={
        "topic": "Тестовая тема", "language": "ru", "cta": "Попробуй бесплатно",
    })
    assert response.status_code == 200
    briefs = client.get("/api/research/briefs", auth=auth).json()
    assert any(b["language"] == "ru" for b in briefs)
