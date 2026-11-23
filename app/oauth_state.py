"""Stateless, short-lived, browser-bound CSRF protection for Threads OAuth.

Signed cookies work across Render process restarts without storing OAuth state in
SQLite (which may be ephemeral on the free tier).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

COOKIE_NAME = "threads_oauth_state"
COOKIE_MAX_AGE_SECONDS = 600


def issue_state_cookie(state: str) -> str:
    key = os.getenv("THREADS_APP_SECRET", "").strip()
    if not key:
        raise ValueError("THREADS_APP_SECRET is missing")
    timestamp = str(int(time.time()))
    unsigned = f"{state}.{timestamp}"
    signature = hmac.new(key.encode(), unsigned.encode(), hashlib.sha256).hexdigest()
    return f"{unsigned}.{signature}"


def verify_state_cookie(cookie: str, supplied_state: str) -> bool:
    key = os.getenv("THREADS_APP_SECRET", "").strip()
    if not key or not cookie or not supplied_state:
        return False
    try:
        saved_state, timestamp, signature = cookie.rsplit(".", 2)
        age = int(time.time()) - int(timestamp)
    except (ValueError, TypeError):
        return False
    if age < -30 or age > COOKIE_MAX_AGE_SECONDS:
        return False
    unsigned = f"{saved_state}.{timestamp}"
    expected_signature = hmac.new(key.encode(), unsigned.encode(), hashlib.sha256).hexdigest()
    return secrets.compare_digest(signature, expected_signature) and secrets.compare_digest(saved_state, supplied_state)
