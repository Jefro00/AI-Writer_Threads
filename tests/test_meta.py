"""Meta public-page and OAuth regression tests; no external Meta requests."""
from __future__ import annotations

import struct
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.config import STATIC_DIR

PUBLIC = ["/meta", "/privacy", "/terms", "/data-deletion"]


def test_meta_policy_pages_public_without_auth(client):
    for path in PUBLIC:
        response = client.get(path)
        assert response.status_code == 200, (path, response.text[:160])
        assert "text/html" in response.headers["content-type"]
        assert "jefrocrypto@gmail.com" in response.text
        assert 'lang="en"' in response.text and 'lang="ru"' in response.text
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "ADMIN_PASSWORD" not in response.text


def test_admin_stays_protected(client):
    assert client.get("/").status_code == 401
    assert client.get("/research").status_code == 401
    assert client.get("/api/posts").status_code == 401


def test_meta_logo_is_1024_and_public(client):
    path = STATIC_DIR / "ai-writer-icon.png"
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", data[16:24]) == (1024, 1024)
    assert len(data) < 5 * 1024 * 1024
    response = client.get("/static/ai-writer-icon.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_oauth_default_does_not_request_unapproved_advanced_scopes(monkeypatch):
    from tools.refresh_threads_token import auth_url, requested_scopes

    monkeypatch.delenv("THREADS_REQUESTED_SCOPES", raising=False)
    monkeypatch.setenv("THREADS_APP_ID", "test-threads-app")
    monkeypatch.setenv("THREADS_REDIRECT_URI", "https://writer.onrender.com/auth/threads/callback")
    monkeypatch.setenv("THREADS_OAUTH_STATE", "random-state-test")
    assert requested_scopes() == ["threads_basic", "threads_content_publish"]
    params = parse_qs(urlparse(auth_url()).query)
    assert params["scope"] == ["threads_basic,threads_content_publish"]
    assert params["redirect_uri"] == ["https://writer.onrender.com/auth/threads/callback"]


def test_oauth_can_add_scopes_after_approval(monkeypatch):
    from tools.refresh_threads_token import requested_scopes
    monkeypatch.setenv("THREADS_REQUESTED_SCOPES", "threads_basic,threads_content_publish,threads_keyword_search")
    assert "threads_keyword_search" in requested_scopes()


def test_oauth_rejects_unknown_and_missing_basic(monkeypatch):
    import pytest
    from tools.refresh_threads_token import requested_scopes
    monkeypatch.setenv("THREADS_REQUESTED_SCOPES", "threads_basic,undocumented_scope")
    with pytest.raises(SystemExit):
        requested_scopes()
    monkeypatch.setenv("THREADS_REQUESTED_SCOPES", "threads_content_publish")
    with pytest.raises(SystemExit):
        requested_scopes()


def test_meta_crawler_not_blocked(client):
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert "Allow: /privacy" in response.text
    assert "Allow: /data-deletion" in response.text
