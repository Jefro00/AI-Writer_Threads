"""Pure helpers shared across collection, analysis and reporting."""
from __future__ import annotations

import hashlib
import ipaddress
import re
import unicodedata
from urllib.parse import parse_qsl, urlparse, urlunparse

# Local/private networks that must never be contacted by link checking (SSRF).
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "metadata.google.internal"}
_SAFE_SCHEMES = {"http", "https"}

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)


def normalize_text(text: str) -> str:
    """Lowercase, strip accents/punctuation noise, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def content_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8", "replace"))
        h.update(b"\x1f")
    return h.hexdigest()


def guess_language(text: str) -> str:
    """Lightweight offline language guess (no external dependency).

    Used only as a default before the AI classifier runs. Cyrillic -> ru,
    Greek -> el, CJK scripts -> zh/ja/ko, otherwise a small stopword score for
    en/es/de/fr/pt/it/tr. Returns 'und' when undetermined.
    """
    if not text:
        return "und"
    if re.search(r"[\u0400-\u04FF]", text):
        return "ru"
    if re.search(r"[\u0370-\u03FF]", text):
        return "el"
    if re.search(r"[\u3040-\u30FF]", text):
        return "ja"
    if re.search(r"[\uAC00-\uD7AF]", text):
        return "ko"
    if re.search(r"[\u4E00-\u9FFF]", text):
        return "zh"

    tokens = set(re.findall(r"[a-zA-Zа-яА-ЯёЁ]+", normalize_text(text)))
    stopwords = {
        "en": {"the", "and", "that", "with", "this", "for", "you", "are", "how", "what", "from", "build", "just"},
        "es": {"que", "con", "para", "por", "una", "los", "las", "como", "más", "pero", "tu", "del"},
        "de": {"und", "der", "die", "das", "mit", "für", "ist", "nicht", "ein", "eine", "wie", "aber"},
        "fr": {"que", "avec", "pour", "dans", "est", "les", "des", "une", "pas", "mais", "vous", "sur"},
        "pt": {"que", "com", "para", "uma", "dos", "das", "não", "mais", "como", "mas", "você"},
        "it": {"che", "con", "per", "una", "gli", "delle", "non", "più", "come", "ma", "sono"},
        "tr": {"ve", "bir", "için", "ile", "bu", "olarak", "çok", "daha", "ama", "sen", "olan"},
    }
    scores = {lang: len(tokens & words) for lang, words in stopwords.items()}
    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    return best if scores[best] >= 2 else "en" if len(tokens) > 4 else "und"


def extract_urls(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in _URL_RE.findall(text or ""):
        url = raw.rstrip(".,;:")
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def is_safe_url(url: str) -> bool:
    """Validate a URL before any outbound request (SSRF / redirect safety)."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme.lower() not in _SAFE_SCHEMES:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or host in _BLOCKED_HOSTS:
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    except ValueError:
        # Hostname: reject obvious local suffixes.
        if host.endswith(".local") or host.endswith(".internal"):
            return False
    return True


def parse_url_details(url: str) -> dict:
    """Return domain, platform type, UTM params, referral flag, clean URL."""
    details: dict = {
        "original_url": url,
        "normalized_url": url,
        "domain": None,
        "platform_type": "website",
        "utm": {},
        "has_referral": False,
    }
    try:
        parsed = urlparse(url)
    except Exception:
        return details
    host = (parsed.hostname or "").lower().lstrip("www.")
    details["domain"] = host or None
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    details["utm"] = {k: v for k, v in params.items() if k.lower().startswith("utm_")}
    ref_keys = {"ref", "ref_id", "referral", "referrer", " affiliate", "aff", "invite", "r"}
    details["has_referral"] = any(k.lower().strip() in ref_keys for k in params)

    platform_map = {
        "t.me": "telegram",
        "telegram.me": "telegram",
        "instagram.com": "instagram",
        "discord.gg": "discord",
        "youtube.com": "youtube",
        "youtu.be": "youtube",
        "medium.com": "medium",
        "substack.com": "newsletter",
        "x.com": "x",
        "twitter.com": "x",
        "github.com": "github",
    }
    for domain, platform in platform_map.items():
        if host == domain or host.endswith("." + domain):
            details["platform_type"] = platform
            break
    clean_query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)]
    details["normalized_url"] = urlunparse(parsed._replace(query="", fragment=""))
    details["query_pairs"] = clean_query
    return details


def build_tracked_url(base: str, post_id: int | str, campaign: str | None = None, source: str = "threads") -> str:
    """Append per-post UTM/referral params to our own base referral URL."""
    from urllib.parse import urlencode

    if not base:
        return base
    sep = "&" if "?" in base else "?"
    params = {
        "utm_source": source,
        "utm_medium": "social",
        "utm_campaign": campaign or f"post-{post_id}",
        "utm_content": f"post-{post_id}",
        "ref": f"threads_post_{post_id}",
    }
    return base + sep + urlencode(params)


def clamp(value: float | None, low: float = 0.0, high: float = 1.0) -> float:
    if value is None:
        return 0.0
    return max(low, min(high, float(value)))


def segment_for_followers(count: int | None) -> str | None:
    if count is None:
        return None
    if count < 1_000:
        return "micro"
    if count < 10_000:
        return "small"
    if count < 50_000:
        return "medium"
    if count < 250_000:
        return "large"
    return "very_large"
