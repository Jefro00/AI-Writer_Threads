"""Data Normalizer: one canonical shape, validation, source tagging."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.database.models import ResearchPost, utcnow
from app.database.repository import get_or_create_profile, get_or_create_source
from app.sources.base import RawPost, RawProfile
from app.utils import extract_urls, guess_language, normalize_text, segment_for_followers, text_hash


def normalize_post(
    db: Session,
    raw: RawPost,
    *,
    source_name: str,
    source_type: str,
    source_id: int | None = None,
) -> ResearchPost:
    text = (raw.text or "").strip()
    if not text:
        raise ValueError("Post text is empty")
    src = source_id
    if src is None:
        src = get_or_create_source(db, source_name, source_type).id

    author = None
    if raw.author_username:
        author, _ = get_or_create_profile(
            db,
            raw.author_username,
            source_id=src,
            profile_url=raw.post_url and _profile_url_from_post(raw.post_url),
            bio=raw.author_bio,
            followers_count=raw.author_followers,
            language=raw.language,
        )

    post = ResearchPost(
        source_id=src,
        external_post_id=raw.external_id,
        author_id=author.id if author else None,
        post_url=raw.post_url,
        original_text=text,
        normalized_text=normalize_text(text),
        text_hash=text_hash(text),
        language=raw.language or guess_language(text),
        published_at=_as_naive(raw.published_at),
        content_type=raw.content_type or "TEXT",
        is_reply=raw.is_reply,
        is_quote=raw.is_quote,
        has_external_link=bool(extract_urls(text)),
        country=None,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    return post


def normalize_profile(db: Session, raw: RawProfile, source_name: str, source_type: str) -> None:
    from app.database.repository import get_or_create_profile

    get_or_create_profile(
        db,
        raw.username,
        source_id=get_or_create_source(db, source_name, source_type).id,
        profile_url=raw.profile_url,
        bio=raw.bio,
        followers_count=raw.followers_count,
        niches=raw.niches,
        language=raw.language,
    )


def _as_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo else value


def _profile_url_from_post(post_url: str) -> str:
    try:
        from urllib.parse import urlparse

        parsed = urlparse(post_url)
        path = parsed.path.strip("/").split("/")
        if path:
            return f"{parsed.scheme}://{parsed.netloc}/@{path[0]}"
    except Exception:
        pass
    return post_url
