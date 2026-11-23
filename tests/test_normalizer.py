"""Text normalization, language and URL safety helpers."""
from __future__ import annotations

from app.utils import (
    build_tracked_url,
    extract_urls,
    guess_language,
    is_safe_url,
    normalize_text,
    parse_url_details,
    text_hash,
)


def test_normalize_text_and_hash():
    a = "  Hello, WORLD!! проверка  "
    b = "hello world проверка"
    assert normalize_text(a) == "hello world проверка"
    assert text_hash(a) == text_hash(b)


def test_language_detection():
    assert guess_language("Это тестовый пост на русском языке") == "ru"
    assert guess_language("the and that with this for you are how what from") == "en"


def test_extract_and_parse_links():
    text = "Смотри https://t.me/jefro?utm_source=threads и https://fomo.family/r/jefrocrypto?ref=x"
    urls = extract_urls(text)
    assert len(urls) == 2
    details = parse_url_details(urls[0])
    assert details["platform_type"] == "telegram"
    assert details["utm"].get("utm_source") == "threads"
    assert parse_url_details(urls[1])["has_referral"] is True


def test_ssrf_url_blocked():
    assert is_safe_url("http://localhost/admin") is False
    assert is_safe_url("http://127.0.0.1:8080") is False
    assert is_safe_url("file:///etc/passwd") is False
    assert is_safe_url("https://example.com/path") is True


def test_tracked_url_has_utm():
    url = build_tracked_url("https://fomo.family/r/jefrocrypto", 42, "launch")
    assert "utm_campaign=launch" in url
    assert "ref=threads_post_42" in url
