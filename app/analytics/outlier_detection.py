"""Outlier detection for unusually successful posts (median-based, robust)."""
from __future__ import annotations

from statistics import median
from typing import Iterable


def median_ratio(value: float | None, med: float | None) -> float | None:
    if value is None or not med or med <= 0:
        return None
    return round(value / med, 2)


def modified_zscore(value: float, values: Iterable[float]) -> float | None:
    vals = [float(v) for v in values]
    if len(vals) < 3:
        return None
    med = median(vals)
    deviations = [abs(v - med) for v in vals]
    mad = median(deviations)
    if mad == 0:
        return None
    return round(0.6745 * (value - med) / mad, 2)


def percentile_rank(value: float, values: Iterable[float]) -> float | None:
    vals = sorted(float(v) for v in values)
    if not vals:
        return None
    below = sum(1 for v in vals if v < value)
    return round(below / len(vals) * 100, 1)


def iqr_bounds(values: Iterable[float]) -> tuple[float, float] | None:
    vals = sorted(float(v) for v in values)
    if len(vals) < 4:
        return None
    mid = len(vals) // 2
    lower = vals[:mid]
    upper = vals[mid:] if len(vals) % 2 == 0 else vals[mid + 1:]
    q1 = median(lower)
    q3 = median(upper)
    iqr = q3 - q1
    return round(q1 - 1.5 * iqr, 2), round(q3 + 1.5 * iqr, 2)


def detect_outliers(posts: list[dict]) -> list[dict]:
    """Annotate each post dict with outlier signals based on `views`.

    `posts` items must have at least {'id': int, 'views': number|None}.
    Uses the author-level baseline passed by the caller via all posts of that
    author. Returns the same list with extra keys.
    """
    views = [p["views"] for p in posts if p.get("views") is not None]
    if not views:
        return posts
    med = median(views)
    bounds = iqr_bounds(views)
    for post in posts:
        v = post.get("views")
        post["median_ratio"] = median_ratio(v, med)
        post["modified_zscore"] = modified_zscore(v, views) if v is not None else None
        post["percentile_rank"] = percentile_rank(v, views) if v is not None else None
        post["is_outlier"] = bool(
            v is not None and ((post["median_ratio"] or 0) >= 3 or (bounds and v > bounds[1]))
        )
    return posts
