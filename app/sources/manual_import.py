"""Manual single-post entry and JSON/CSV import (always available, no API needed)."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any

from .base import SourceAdapter, SourceResult, RawPost, RawProfile


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (ValueError, TypeError):
        return None


class ManualImportSource(SourceAdapter):
    name = "manual"
    source_type = "manual"

    async def collect(self, params: dict) -> SourceResult:
        """Convert one manually entered payload (or a list) into RawPosts."""
        result = SourceResult()
        items = params.get("items")
        if items is None:
            items = [params]
        elif isinstance(items, dict):
            items = [items]
        for item in items:
            if not isinstance(item, dict):
                result.errors.append("Import item is not an object")
                continue
            text = str(item.get("text") or item.get("original_text") or "").strip()
            post_url = item.get("post_url") or item.get("url") or item.get("permalink")
            if not text and not post_url:
                result.errors.append("Skipped item without text or URL")
                continue
            author = item.get("author") or item.get("author_username") or item.get("username")
            metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else item
            result.posts.append(
                RawPost(
                    external_id=str(item.get("external_post_id") or item.get("id") or "") or None,
                    text=text or str(post_url),
                    author_username=str(author).lstrip("@") if author else None,
                    post_url=str(post_url) if post_url else None,
                    published_at=_parse_dt(item.get("published_at") or item.get("date")),
                    language=item.get("language"),
                    content_type=item.get("content_type") or "TEXT",
                    is_reply=bool(item.get("is_reply", False)),
                    is_quote=bool(item.get("is_quote", False)),
                    views=_as_int(metrics.get("views")),
                    likes=_as_int(metrics.get("likes")),
                    replies=_as_int(metrics.get("replies")),
                    reposts=_as_int(metrics.get("reposts")),
                    quotes=_as_int(metrics.get("quotes")),
                    author_followers=_as_int(metrics.get("followers") or metrics.get("followers_count")),
                    author_bio=item.get("author_bio") or item.get("bio"),
                    raw=item,
                )
            )
            if author:
                result.profiles.append(
                    RawProfile(
                        username=str(author).lstrip("@"),
                        profile_url=item.get("author_url") or item.get("profile_url"),
                        bio=item.get("author_bio") or item.get("bio"),
                        followers_count=_as_int(metrics.get("followers") or metrics.get("followers_count")),
                        language=item.get("language"),
                        niches=item.get("niches") or [],
                    )
                )
        return result

    @staticmethod
    def parse_file(filename: str, content: bytes) -> list[dict]:
        """Parse JSON or CSV bytes into a list of flat dicts."""
        lower = filename.lower()
        if lower.endswith(".json"):
            data = json.loads(content.decode("utf-8-sig"))
            if isinstance(data, dict):
                data = data.get("items", data.get("posts", [data]))
            if not isinstance(data, list):
                raise ValueError("JSON root must be an array or an object with 'items'")
            return [row for row in data if isinstance(row, dict)]

        if lower.endswith(".csv"):
            text = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            rows: list[dict] = []
            for row in reader:
                clean = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
                flat: dict[str, Any] = dict(clean)
                # Allow nested-style columns: metrics.views, author.username, etc.
                metrics = {k.split(".", 1)[1]: v for k, v in clean.items() if "." in k and k.startswith("metrics.")}
                if metrics:
                    flat["metrics"] = metrics
                rows.append(flat)
            return rows

        raise ValueError("Unsupported file type. Use .json or .csv")
