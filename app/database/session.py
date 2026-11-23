"""Engine / session factory shared by the Writer and the Research Engine.

The original starter created these objects inside ``app/main.py``. They now
live here so research models, background workers and scripts can all share the
exact same ``Base.metadata`` and connection pool. Existing Writer behaviour is
unchanged.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.orm import Session

from app.config import settings


def _connect_args(url: str) -> dict:
    return {"check_same_thread": False} if url.startswith("sqlite") else {}


DATABASE_URL: str = settings.database_url
engine: Engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args(DATABASE_URL),
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record) -> None:
    """Allow concurrent readers/writers (API + scheduler + CLI in one DB)."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped session.

    Research routes use flush()/flush-based helpers and rely on this dependency
    to commit at the end of a successful request. The Writer routes use their
    own explicit sessions and are unaffected.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create all tables and add new columns to existing databases.

    ``create_all`` never alters existing tables, so small additive schema
    changes are applied explicitly. This keeps the original DB (and its Writer
    drafts) intact across updates.
    """
    from sqlalchemy import inspect, text

    from app.database import models  # noqa: F401

    Base.metadata.create_all(engine)
    # Additive migrations retain existing Writer drafts and research tables.
    # Names/DDL are fixed constants and never built from user input.
    additive_columns = {
        "posts": {
            "language": "VARCHAR(20) DEFAULT 'ru'",
            "campaign_id": "INTEGER",
            "offer_id": "INTEGER",
            "goal": "VARCHAR(30) DEFAULT 'discussion'",
            "hook_type": "VARCHAR(40)",
            "variant_index": "INTEGER",
            "editorial_score": "FLOAT",
            "prompt_version": "VARCHAR(40)",
            "ai_model": "VARCHAR(120)",
            "tracking_url": "VARCHAR(1000)",
        },
        "writer_briefs": {"language": "VARCHAR(20) DEFAULT 'ru'"},
    }
    inspector = inspect(engine)
    for table, columns in additive_columns.items():
        if table not in inspector.get_table_names():
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        for column, ddl in columns.items():
            if column not in existing:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    # Seed the FOMO offer once. An existing offer is never overwritten on reboot.
    from sqlalchemy import select
    from app.database.models import AffiliateOffer
    with SessionLocal() as db:
        if not db.scalar(select(AffiliateOffer).where(AffiliateOffer.slug == "fomo")):
            db.add(AffiliateOffer(
                slug="fomo", name="FOMO", referral_url=settings.base_referral_url,
                description="Поиск криптоактивов и активность трейдеров. Не обещать доходность.",
                target_audience="Криптоэнтузиасты, мемкоины, исследование рынка",
                benefits_json=[],
            ))
            db.commit()
