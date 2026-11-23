"""Central configuration for JefroCrypto Threads Engine.

All secrets stay in environment variables. Nothing here is ever sent to the
browser. This module is intentionally dependency-light so it can be imported
from anywhere (models, workers, scripts) without circular imports.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# .env next to the project root is loaded once at import time.
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
DB_FALLBACK = f"sqlite:///{BASE_DIR / 'threads_engine.db'}"


def _database_url() -> str:
    url = os.getenv("DATABASE_URL") or DB_FALLBACK
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


class Settings:
    """Runtime settings read from environment at access time.

    Reading at access time (instead of caching at import) keeps the app easy to
    test with monkeypatched environment variables.
    """

    APP_NAME = "JefroCrypto Threads Engine"
    APP_VERSION = "0.3.2"

    @property
    def database_url(self) -> str:
        return _database_url()

    @property
    def admin_username(self) -> str:
        return os.getenv("ADMIN_USERNAME", "admin")

    @property
    def admin_password(self) -> str:
        return os.getenv("ADMIN_PASSWORD", "")

    @property
    def gemini_api_key(self) -> str:
        return os.getenv("GEMINI_API_KEY", "").strip()

    @property
    def gemini_model(self) -> str:
        return os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

    @property
    def openrouter_api_key(self) -> str:
        return os.getenv("OPENROUTER_API_KEY", "").strip()

    @property
    def openrouter_model(self) -> str:
        return os.getenv("OPENROUTER_MODEL", "openrouter/free")

    @property
    def ai_provider_order(self) -> list[str]:
        # OpenRouter is first by default: the free Gemini endpoint can be
        # unreachable/slow from some cloud regions. Gemini stays supported and
        # can be made first with AI_PROVIDER_ORDER=gemini,openrouter.
        raw = os.getenv("AI_PROVIDER_ORDER", "openrouter,gemini")
        return [p.strip().lower() for p in raw.split(",") if p.strip()]

    @property
    def threads_access_token(self) -> str:
        return os.getenv("THREADS_ACCESS_TOKEN", "").strip()

    @property
    def threads_api_base(self) -> str:
        return os.getenv("THREADS_API_BASE", "https://graph.threads.net/v1.0")

    @property
    def content_library_token(self) -> str:
        return os.getenv("META_CONTENT_LIBRARY_TOKEN", "").strip()

    @property
    def threads_keyword_search_enabled(self) -> bool:
        """True only after Meta approves the threads_keyword_search scope."""
        return os.getenv("THREADS_KEYWORD_SEARCH_ENABLED", "false").lower() in {"1", "true", "yes", "on"}

    @property
    def threads_own_username(self) -> str:
        """Known connected Threads handle, used to omit own posts from research."""
        return os.getenv("THREADS_OWN_USERNAME", "").strip().lstrip("@").lower()

    @property
    def threads_profile_discovery_enabled(self) -> bool:
        """Allows polling authors by username via /profile_posts and /profile_lookup."""
        return os.getenv("THREADS_PROFILE_DISCOVERY_ENABLED", "false").lower() in {"1", "true", "yes", "on"}

    @property
    def max_import_bytes(self) -> int:
        try:
            return int(os.getenv("MAX_IMPORT_BYTES", str(5 * 1024 * 1024)))
        except ValueError:
            return 5 * 1024 * 1024

    @property
    def request_timeout(self) -> float:
        try:
            return float(os.getenv("AI_REQUEST_TIMEOUT", "50"))
        except ValueError:
            return 50.0

    @property
    def research_enabled_sources(self) -> set[str]:
        raw = os.getenv("RESEARCH_ENABLED_SOURCES", "manual,threads_api,content_library,account_monitor")
        return {p.strip().lower() for p in raw.split(",") if p.strip()}

    @property
    def base_referral_url(self) -> str:
        return os.getenv("BASE_REFERRAL_URL", "https://fomo.family/r/jefrocrypto")

    @property
    def public_base_url(self) -> str:
        """Public HTTPS origin for click redirect URLs; leave unset for raw affiliate links."""
        raw = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
        return raw if raw.startswith("https://") and "/" not in raw[8:] else ""

    @property
    def default_language(self) -> str:
        return os.getenv("DEFAULT_POST_LANGUAGE", "ru").strip().lower() or "ru"

    @property
    def scheduler_enabled(self) -> bool:
        return os.getenv("RESEARCH_SCHEDULER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}

    @property
    def auto_publish_enabled(self) -> bool:
        return os.getenv("AUTO_PUBLISH_ENABLED", "false").lower() in {"1", "true", "yes", "on"}

    @property
    def auto_publish_require_approval(self) -> bool:
        # Default True: only already-approved drafts are published (matches TЗ).
        return os.getenv("AUTO_PUBLISH_REQUIRE_APPROVAL", "true").lower() in {"1", "true", "yes", "on"}

    @property
    def auto_publish_interval_seconds(self) -> int:
        try:
            return max(30, int(os.getenv("AUTO_PUBLISH_INTERVAL_SECONDS", "300")))
        except ValueError:
            return 300

    @property
    def auto_publish_batch_size(self) -> int:
        try:
            return max(1, min(20, int(os.getenv("AUTO_PUBLISH_BATCH_SIZE", "3"))))
        except ValueError:
            return 3


settings = Settings()
