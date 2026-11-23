"""Security-related checks."""
from __future__ import annotations

from app.utils import build_tracked_url, is_safe_url


def test_no_token_in_frontend_files():
    from pathlib import Path
    static = Path(__file__).resolve().parent.parent / "app" / "static"
    for path in static.glob("*"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "API_KEY" not in text
        assert "ACCESS_TOKEN" not in text


def test_referral_url_is_tracked_per_post():
    one = build_tracked_url("https://fomo.family/r/jefrocrypto", 1)
    two = build_tracked_url("https://fomo.family/r/jefrocrypto", 2)
    assert one != two
    assert "utm_content=post-1" in one


def test_private_network_urls_blocked():
    for url in [
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://[::1]/",
    ]:
        assert is_safe_url(url) is False
