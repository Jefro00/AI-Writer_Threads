"""AI layer unit tests (no real API calls)."""
from __future__ import annotations

import pytest

from app.ai.provider import _extract_json, ai_configured
from app.ai.prompts import PROMPT_VERSIONS
from app.ai.tasks import needs_analysis


def test_extract_json_variants():
    assert _extract_json('{"a": 1}') == {"a": 1}
    assert _extract_json('```json\n{"b": 2}\n```') == {"b": 2}
    assert _extract_json('noise {"c": 3} noise') == {"c": 3}
    assert _extract_json("not json") == {}


def test_prompt_versions_exist():
    for agent in ["content_classifier", "strategy_analyzer", "cta_analyzer", "funnel_analyzer", "viral_detector"]:
        assert PROMPT_VERSIONS[agent].startswith("v")


def test_no_ai_configured_returns_false():
    assert ai_configured() is False  # env cleared in conftest
