"""Check which Threads scopes the current .env token actually has.

Run: python tools/check_threads_token.py
It prints only scope names and booleans — never the token itself.
"""
from __future__ import annotations

from pathlib import Path

import httpx
from dotenv import load_dotenv
import os

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
TOKEN = os.getenv("THREADS_ACCESS_TOKEN", "").strip()
BASE = os.getenv("THREADS_API_BASE", "https://graph.threads.net/v1.0").rstrip("/")

if not TOKEN:
    raise SystemExit("THREADS_ACCESS_TOKEN is empty in .env")

with httpx.Client(timeout=30.0) as client:
    me = client.get(f"{BASE}/me", params={
        "fields": "id,username", "access_token": TOKEN,
    })
    print("GET /me:", me.status_code)
    if me.status_code == 200:
        print("  account:", me.json().get("username"))
    else:
        print(" ", me.text[:300])

    # Each endpoint is a direct probe of one scope.
    probes = {
        "threads_basic": ("GET", f"{BASE}/me", {"fields": "id", "access_token": TOKEN}),
        "threads_manage_insights": ("GET", f"{BASE}/me/threads_insights", {"metric": "views", "access_token": TOKEN}),
        "threads_keyword_search": ("GET", f"{BASE}/keyword_search", {
            "q": "solana", "limit": 1, "access_token": TOKEN,
        }),
        "threads_profile_discovery": ("GET", f"{BASE}/profile_lookup", {
            "username": os.getenv("THREADS_TEST_USERNAME", "web3sergeich"),
            "access_token": TOKEN,
        }),
    }
    for scope, (method, url, params) in probes.items():
        try:
            r = client.request(method, url, params=params)
            granted = r.status_code < 400
            detail = "" if granted else f" — {r.text[:260]}"
            if not granted and "4279067" in r.text:
                detail += " [APP REVIEW / ADVANCED ACCESS REQUIRED]"
        except httpx.HTTPError as exc:
            granted, detail = False, f" — {type(exc).__name__}"
        print(f"{scope}: {'OK' if granted else 'MISSING / ERROR'}{detail}")
