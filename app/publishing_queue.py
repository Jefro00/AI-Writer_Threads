"""Atomic claim + cautious failure state to avoid duplicate Threads posts."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import update

from app.database.models import Post, utcnow
from app.database.session import SessionLocal
from app import publisher


async def publish_claimed(post_id: int, *, allow_unapproved: bool = False):
    allowed = ["approved"] + (["pending_review", "draft"] if allow_unapproved else [])
    with SessionLocal() as db:
        claimed = db.execute(
            update(Post).where(Post.id == post_id, Post.status.in_(allowed),
                               Post.threads_post_id.is_(None))
            .values(status="publishing")
        )
        db.commit()
        if claimed.rowcount != 1:
            raise HTTPException(409, "Пост не одобрен, уже публикуется или опубликован")
        post = db.get(Post, post_id)
        text = post.text
    try:
        result = await publisher.publish_text(text)
    except Exception as exc:
        # Transport timeout / Meta error may happen after the remote publish.
        # NEVER auto-retry an ambiguous attempt: user must inspect Threads.
        with SessionLocal() as db:
            db.execute(update(Post).where(Post.id == post_id, Post.status == "publishing")
                       .values(status="publish_uncertain"))
            db.commit()
        if isinstance(exc, publisher.ThreadsPublishError):
            raise HTTPException(502, str(exc)) from exc
        raise HTTPException(502, f"Не удалось подтвердить публикацию: {type(exc).__name__}") from exc
    with SessionLocal() as db:
        db.execute(update(Post).where(Post.id == post_id, Post.status == "publishing")
                   .values(status="published", threads_post_id=result.threads_post_id,
                           published_at=utcnow()))
        db.commit()
        return result
