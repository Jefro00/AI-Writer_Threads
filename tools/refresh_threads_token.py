"""Helper for re-issuing a Threads token with all required scopes.

Why this exists: adding a permission in the Meta App Dashboard does NOT add it
to an already-issued access token. You must authorize the app again and exchange
the new code for a fresh long-lived token.

Usage (PowerShell, from the project root):

    # 1) print the authorization URL, open it in a browser, approve
    python tools/refresh_threads_token.py url

    # 2) after the redirect, copy the `code` value and run:
    python tools/refresh_threads_token.py exchange "<CODE>"

    # 3) later, refresh an unexpired long-lived token:
    python tools/refresh_threads_token.py refresh

  Alternative if an HTTPS callback is not yet available:
    generate a short-lived token in Graph API Explorer with all scopes, then:
    python tools/refresh_threads_token.py exchange-short "<SHORT_TOKEN>"

The resulting token is written straight into .env (never printed).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
import os

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Only request scopes approved for this app. Requesting Advanced Access scopes
# before they are approved can break the initial OAuth flow.
KNOWN_SCOPES = frozenset({
    "threads_basic", "threads_content_publish", "threads_keyword_search",
    "threads_profile_discovery", "threads_manage_insights",
    "threads_read_replies", "threads_manage_replies",
})


def requested_scopes() -> list[str]:
    raw = os.getenv("THREADS_REQUESTED_SCOPES", "threads_basic,threads_content_publish")
    scopes = list(dict.fromkeys(v.strip() for v in raw.split(",") if v.strip()))
    if not scopes or any(scope not in KNOWN_SCOPES for scope in scopes):
        raise SystemExit("Invalid THREADS_REQUESTED_SCOPES. See .env.example.")
    if "threads_basic" not in scopes:
        raise SystemExit("THREADS_REQUESTED_SCOPES must include threads_basic.")
    return scopes


BASE = "https://graph.threads.com"
AUTH_URL = "https://threads.com/oauth/authorize"


def _cfg(name: str) -> str:
    return os.getenv(name, "").strip()


def _require(name: str) -> str:
    value = _cfg(name)
    if not value:
        raise SystemExit(
            f"Set {name} in .env first (see .env.example). "
            "Copy it from Meta App Dashboard → App settings → Basic."
        )
    return value


def auth_url(redirect_override: str | None = None) -> str:
    app_id = _require("THREADS_APP_ID")
    redirect = redirect_override or _require("THREADS_REDIRECT_URI")
    if redirect.startswith("http://") and "localhost" not in redirect:
        raise SystemExit("Meta requires an HTTPS redirect_uri.")
    params = {
        "client_id": app_id,
        "redirect_uri": redirect,
        "scope": ",".join(requested_scopes()),
        "response_type": "code",
        "state": _require("THREADS_OAUTH_STATE"),
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _write_token(token: str) -> None:
    env_path = ROOT / ".env"
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    line = f"THREADS_ACCESS_TOKEN={token}"
    if re.search(r"^THREADS_ACCESS_TOKEN=.*$", text, flags=re.MULTILINE):
        text = re.sub(r"^THREADS_ACCESS_TOKEN=.*$", line, text, flags=re.MULTILINE)
    else:
        text = text.rstrip() + "\n" + line + "\n"
    env_path.write_text(text, encoding="utf-8")
    print("New token written to .env successfully")
    print("Restart the server to pick it up.")


def exchange(code: str, redirect_override: str | None = None) -> None:
    app_id = _require("THREADS_APP_ID")
    secret = _require("THREADS_APP_SECRET")
    redirect = redirect_override or _require("THREADS_REDIRECT_URI")
    with httpx.Client(timeout=40.0) as client:
        short = client.post(
            f"{BASE}/oauth/access_token",
            data={
                "client_id": app_id,
                "client_secret": secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect,
                "code": code.split("#_")[0],
            },
        )
        if short.status_code >= 400:
            raise SystemExit(f"Code exchange failed HTTP {short.status_code}: {short.text[:400]}")
        short_token = short.json()["access_token"]
        long = client.get(
            f"{BASE}/access_token",
            params={
                "grant_type": "th_exchange_token",
                "client_secret": secret,
                "access_token": short_token,
            },
        )
        if long.status_code >= 400:
            raise SystemExit(f"Long-lived exchange failed HTTP {long.status_code}: {long.text[:400]}")
        _write_token(long.json()["access_token"])


def promote_short(short_token: str) -> None:
    """Exchange a short-lived token (e.g. from Graph API Explorer) for long-lived."""
    secret = _require("THREADS_APP_SECRET")
    with httpx.Client(timeout=40.0) as client:
        response = client.get(
            f"{BASE}/access_token",
            params={
                "grant_type": "th_exchange_token",
                "client_secret": secret,
                "access_token": short_token.split("#_")[0],
            },
        )
    if response.status_code >= 400:
        raise SystemExit(f"Long-lived exchange failed HTTP {response.status_code}: {response.text[:400]}")
    _write_token(response.json()["access_token"])


def refresh() -> None:
    token = _cfg("THREADS_ACCESS_TOKEN")
    if not token:
        raise SystemExit("THREADS_ACCESS_TOKEN is empty; run the authorization flow instead.")
    with httpx.Client(timeout=40.0) as client:
        response = client.get(
            f"{BASE}/refresh_access_token",
            params={"grant_type": "th_refresh_token", "access_token": token},
        )
    if response.status_code >= 400:
        raise SystemExit(f"Refresh failed HTTP {response.status_code}: {response.text[:400]}")
    _write_token(response.json()["access_token"])


def main() -> None:
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "help"
    redirect_override = sys.argv[3] if len(sys.argv) > 3 else None
    if mode == "url":
        print(auth_url(redirect_override))
    elif mode == "exchange" and len(sys.argv) > 2:
        exchange(sys.argv[2], redirect_override)
    elif mode in {"short", "exchange-short"} and len(sys.argv) > 2:
        promote_short(sys.argv[2])
    elif mode == "refresh":
        refresh()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
