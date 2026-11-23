"""SQLite backup helper (safe online copy via SQLite backup API)."""
from __future__ import annotations

import io
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import DB_FALLBACK, settings


def create_backup(db: Session) -> tuple[bytes, str]:
    """Return (bytes, filename). Works for SQLite; other dialects are unsupported."""
    url = settings.database_url
    if not url.startswith("sqlite"):
        raise RuntimeError("Automatic backup is only implemented for SQLite")
    source = url.replace("sqlite:///", "")
    if source == "" or source.startswith(":memory:"):
        raise RuntimeError("In-memory database cannot be backed up this way")
    source_path = Path(source)
    if not source_path.is_absolute():
        source_path = Path.cwd() / source_path
    import sqlite3

    dest = io.BytesIO()
    with sqlite3.connect(str(source_path)) as src, sqlite3.connect(":memory:") as tmp:
        src.backup(tmp)
        for line in tmp.iterdump():
            dest.write((line + "\n").encode("utf-8"))
    db.execute(text("SELECT 1"))
    return dest.getvalue(), f"threads_engine_backup_{source_path.stem}.sql"
