"""Writer regression + Research API lifecycle."""
from __future__ import annotations

from app.database.models import Post as WriterPost
from app.database.session import SessionLocal


def test_writer_health_and_unchanged_routes(client, auth):
    health = client.get("/api/health", auth=auth).json()
    assert health["ok"] is True
    assert health["research_enabled"] is True
    # Writer still lists its own posts table.
    assert client.get("/api/posts", auth=auth).status_code == 200
    with SessionLocal() as db:
        assert db.query(WriterPost).count() >= 0


def test_admin_protection(client):
    assert client.get("/api/research/overview").status_code == 401
    assert client.get("/api/research/posts").status_code == 401


def test_empty_report_is_rejected(monkeypatch, client, auth):
    import app.api.research as api

    monkeypatch.setattr(api, "count_posts", lambda db: 0)
    response = client.post("/api/research/reports", auth=auth, json={"title": "Empty", "days": 30})
    assert response.status_code == 409
    assert "Нет публикаций" in response.json()["detail"]


def test_full_research_lifecycle(client, auth):
    created = client.post("/api/research/posts/manual", auth=auth, json={
        "text": "Lifecycle test post about a free tool for founders.",
        "views": 500, "likes": 25, "replies": 5, "reposts": 3,
    })
    assert created.status_code == 200
    post_id = client.get("/api/research/posts", auth=auth).json()["items"][0]["id"]

    detail = client.get(f"/api/research/posts/{post_id}", auth=auth).json()
    assert detail["metrics"]["engagement_rate"] is not None
    assert detail["metrics"]["views"] == 500

    metric = client.post(f"/api/research/posts/{post_id}/metric", auth=auth, json={
        "views": 12000, "likes": 900, "replies": 60, "reposts": 40,
    })
    assert metric.status_code == 200
    detail2 = client.get(f"/api/research/posts/{post_id}", auth=auth).json()
    assert len(detail2["metrics_history"]) >= 2
    assert detail2["metrics"]["views"] == 12000

    overview = client.get("/api/research/overview", auth=auth).json()
    assert overview["counts"]["posts"] >= 1
    assert "sources" in overview

    status = client.get("/api/research/status", auth=auth).json()
    assert "latest" in status

    jobs = client.get("/api/research/jobs", auth=auth).json()
    assert jobs and jobs[0]["found"] >= 1
