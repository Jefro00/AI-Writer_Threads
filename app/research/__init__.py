"""Research data pipeline."""
from .collector import collect_from_source, persist_raw_post
from .normalizer import normalize_post, normalize_profile
from .deduplicator import deduplicate
from .keyword_search import expand_keywords, NICHES
from .account_monitor import monitored_handles
from .product_discovery import upsert_product_from_link, upsert_product_from_name, apply_landing_card
from .funnel_detector import process_funnel_analysis, max_proof

__all__ = [
    "collect_from_source", "persist_raw_post", "normalize_post", "normalize_profile",
    "deduplicate", "expand_keywords", "NICHES", "monitored_handles",
    "upsert_product_from_link", "upsert_product_from_name", "apply_landing_card",
    "process_funnel_analysis", "max_proof",
]
