"""Free-first AI provider interface.

Gemini is the first provider; OpenRouter is an interchangeable fallback. Both
return structured JSON. No hard dependency on a single model. No API key ever
leaves the server.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

from app.config import settings


class AIError(RuntimeError):
    pass


def _extract_json(text: str) -> dict:
    """Parse a JSON object from a model reply, tolerating code fences/noise."""
    if not text:
        return {}
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start:end + 1])
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    return {}


async def _gemini(prompt: str, system: str, timeout: float) -> tuple[dict, str]:
    key = settings.gemini_api_key
    if not key:
        raise AIError("GEMINI_API_KEY not configured")
    model = settings.gemini_model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    payload: dict[str, Any] = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 4096,
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0)) as client:
        response = await client.post(url, params={"key": key}, json=payload)
    if response.status_code >= 400:
        raise AIError(f"Gemini HTTP {response.status_code}: {response.text[:200]}")
    data = response.json()
    text = ""
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    except (KeyError, IndexError, TypeError):
        raise AIError("Gemini returned an unexpected response")
    return _extract_json(text), text


async def _openrouter(prompt: str, system: str, timeout: float) -> tuple[dict, str]:
    key = settings.openrouter_api_key
    if not key:
        raise AIError("OPENROUTER_API_KEY not configured")
    model = settings.openrouter_model
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 4096,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0)) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://jefrocrypto.local",
                "X-OpenRouter-Title": settings.APP_NAME,
            },
            json=payload,
        )
    if response.status_code >= 400:
        raise AIError(f"OpenRouter HTTP {response.status_code}: {response.text[:200]}")
    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise AIError("OpenRouter returned an unexpected response")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return _extract_json(str(content)), str(content)


async def ai_json(prompt: str, system: str = "") -> dict:
    """Get a structured JSON object from the first available provider."""
    timeout = settings.request_timeout
    # Fail fast on an unreachable Gemini endpoint so the fallback can run.
    gemini_timeout = min(timeout, 20.0)
    errors: list[str] = []
    for provider in settings.ai_provider_order:
        try:
            if provider == "gemini":
                data, _ = await _gemini(prompt, system, gemini_timeout)
            elif provider == "openrouter":
                data, _ = await _openrouter(prompt, system, timeout)
            else:
                continue
            if data:
                return data
            errors.append(f"{provider}: empty/invalid JSON")
        except (AIError, httpx.HTTPError, asyncio.TimeoutError) as exc:
            errors.append(f"{provider}: {exc}")
    raise AIError("All AI providers failed: " + "; ".join(errors))


def ai_configured() -> bool:
    return bool(settings.gemini_api_key or settings.openrouter_api_key)
