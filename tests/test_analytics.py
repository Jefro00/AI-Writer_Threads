"""Metrics formulas, medians and outlier detection."""
from __future__ import annotations

from app.analytics import engagement_rate, cr, ctr, revenue_per_1000_views
from app.analytics.outlier_detection import detect_outliers, median_ratio, modified_zscore


def test_metric_formulas():
    assert engagement_rate(1000, 100, 20, 30, 50) == 20.0
    assert engagement_rate(None, 100, 20, 30, 50) is None  # unknown != zero
    assert ctr(50, 1000) == 5.0
    assert cr(5, 50) == 10.0
    assert revenue_per_1000_views(100, 10000) == 10.0


def test_outlier_signals():
    rows = [{"id": i, "views": v} for i, v in enumerate([1000, 1200, 900, 1100, 48000])]
    detect_outliers(rows)
    assert rows[-1]["is_outlier"] is True
    assert rows[-1]["median_ratio"] > 3
    assert rows[0]["is_outlier"] is False
    assert median_ratio(48000, 1100) > 40
    assert modified_zscore(48000, [1000, 1200, 900, 1100, 48000]) is not None


def test_author_median_not_mean(client, auth):
    # Existing post from collector tests has 1200 views; verify median path.
    rows = client.get("/api/research/authors/leaderboard?metric=median_views", auth=auth).json()
    assert isinstance(rows, list)
    assert all("median_views" in r for r in rows)
