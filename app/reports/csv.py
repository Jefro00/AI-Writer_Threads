"""CSV export helpers."""
from __future__ import annotations

import csv
import io


def posts_to_csv(rows: list[dict]) -> str:
    fields = [
        "id", "author", "language", "niche", "format", "views", "likes",
        "replies", "reposts", "quotes", "engagement_rate", "post_url", "text",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k) for k in fields})
    return buf.getvalue()
