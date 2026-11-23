"""Deduplication: (source_id, external_post_id) unique, plus text-hash fallback."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ResearchPost
from app.database.repository import find_post_by_external_id


def deduplicate(
    db: Session, post: ResearchPost
) -> tuple[bool, str]:
    """Return (is_duplicate, reason).

    Primary rule: same source + same external id.
    Fallback: identical normalized-text hash (cross-source reposts) within the
    same author, or identical URL.
    """
    if post.external_post_id and post.source_id:
        existing = find_post_by_external_id(db, post.source_id, post.external_post_id)
        if existing:
            return True, "same_source_external_id"

    if post.post_url:
        by_url = db.scalar(select(ResearchPost).where(ResearchPost.post_url == post.post_url))
        if by_url:
            return True, "same_url"

    if post.text_hash:
        query = select(ResearchPost).where(ResearchPost.text_hash == post.text_hash)
        if post.author_id:
            query = query.where(ResearchPost.author_id == post.author_id)
        existing = db.scalars(query.limit(1)).first()
        if existing:
            return True, "same_text_hash"
    return False, ""
