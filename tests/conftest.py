"""Test fixtures: isolated SQLite DB, no network calls, no real AI keys."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

TEST_DB = Path(__file__).resolve().parent / "_test.db"

# Must be set at CONftest import time (before test modules import app.*): the
# SQLAlchemy engine captures DATABASE_URL at module import.
for suffix in ("", "-wal", "-shm"):
    _path = Path(str(TEST_DB) + suffix)
    if _path.exists():
        _path.unlink()
os.environ.update({
    "ADMIN_USERNAME": "admin",
    "ADMIN_PASSWORD": "testpass",
    "GEMINI_API_KEY": "",
    "OPENROUTER_API_KEY": "",
    "THREADS_ACCESS_TOKEN": "",
    "META_CONTENT_LIBRARY_TOKEN": "",
    "RESEARCH_SCHEDULER_ENABLED": "false",
    "DATABASE_URL": f"sqlite:///{TEST_DB}",
})


@pytest.fixture(scope="session", autouse=True)
def env_setup():
    yield


@pytest.fixture(scope="session")
def client(env_setup):
    from fastapi.testclient import TestClient
    from app.database.session import Base, engine, init_db
    from app.main import app as fastapi_app

    init_db()
    with TestClient(fastapi_app) as c:
        yield c


@pytest.fixture
def auth():
    return ("admin", "testpass")
