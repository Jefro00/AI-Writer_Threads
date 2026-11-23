"""DB-driven account monitoring helper."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import TrackedProfile


def monitored_handles(db: Session) -> dict[str, str | None]:
    """Return all tracked authors as {username: external_profile_id or None}.

    A numeric ID is optional: with `threads_profile_discovery` the API can poll
    `/profile_posts?username=...` directly.
    """
    rows = db.scalars(select(TrackedProfile)).all()
    return {r.username: r.external_profile_id for r in rows}
