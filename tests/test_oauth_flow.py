"""End-to-end local-only tests for browser-bound Render OAuth flow."""
from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient


def test_oauth_start_requires_admin(client):
    response = client.get("/auth/threads/start", follow_redirects=False)
    assert response.status_code == 401


def test_oauth_start_callback_roundtrip_same_browser(monkeypatch):
    from app.main import app

    monkeypatch.setenv("THREADS_APP_ID", "test-threads-id")
    monkeypatch.setenv("THREADS_APP_SECRET", "test-secret-not-real")
    monkeypatch.setenv("THREADS_REDIRECT_URI", "https://ai-writer-threads.onrender.com/auth/threads/callback")
    monkeypatch.delenv("THREADS_OAUTH_STATE", raising=False)
    monkeypatch.delenv("THREADS_REQUESTED_SCOPES", raising=False)

    with TestClient(app, base_url="https://ai-writer-threads.onrender.com") as browser:
        initial = browser.get("/auth/threads/start", auth=("admin", "testpass"), follow_redirects=False)
        assert initial.status_code == 302
        assert "HttpOnly" in initial.headers["set-cookie"]
        assert "Secure" in initial.headers["set-cookie"]
        assert "samesite=lax" in initial.headers["set-cookie"].lower()
        assert "no-store" == initial.headers["cache-control"]
        params = parse_qs(urlparse(initial.headers["location"]).query)
        assert params["client_id"] == ["test-threads-id"]
        assert params["redirect_uri"] == ["https://ai-writer-threads.onrender.com/auth/threads/callback"]
        state = params["state"][0]
        assert len(state) >= 32

        bad = browser.get("/auth/threads/callback", params={"code": "test-code", "state": state + "tamper"})
        assert bad.status_code == 400
        assert "test-code" not in bad.text

        result = browser.get("/auth/threads/callback", params={"code": "test-code", "state": state})
        assert result.status_code == 200
        assert "Код получен" in result.text
        assert "test-code" in result.text
        assert 'max-age=0' in result.headers["set-cookie"].lower()

        replay = browser.get("/auth/threads/callback", params={"code": "test-code", "state": state})
        assert replay.status_code == 400


def test_callback_direct_url_explains_how_to_start(client):
    result = client.get("/auth/threads/callback")
    assert result.status_code == 400
    assert "/auth/threads/start" in result.text


def test_oauth_requires_app_secret(monkeypatch, client):
    monkeypatch.setenv("THREADS_APP_SECRET", "")
    res = client.get("/auth/threads/start", auth=("admin", "testpass"), follow_redirects=False)
    assert res.status_code == 503
    assert "THREADS_APP_SECRET" in res.text


def test_browser_oauth_cookie_has_expiration(monkeypatch):
    from app import oauth_state

    monkeypatch.setenv("THREADS_APP_SECRET", "not-a-real-secret")
    monkeypatch.setattr(oauth_state.time, "time", lambda: 1700000000)
    state = "random-test-state"
    cookie = oauth_state.issue_state_cookie(state)
    assert oauth_state.verify_state_cookie(cookie, state)
    monkeypatch.setattr(oauth_state.time, "time", lambda: 1700000700)
    assert not oauth_state.verify_state_cookie(cookie, state)
    assert not oauth_state.verify_state_cookie(cookie, "wrong-state")
    assert not oauth_state.verify_state_cookie(cookie[:-1] + "0", state)


def test_legacy_state_supported(monkeypatch, client):
    monkeypatch.setenv("THREADS_OAUTH_STATE", "legacy-random-state")
    response = client.get("/auth/threads/callback", params={"state": "legacy-random-state", "code": "legacy-code"})
    assert response.status_code == 200
    assert "legacy-code" in response.text
