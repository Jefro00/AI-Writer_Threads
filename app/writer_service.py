"""Shared generation logic for the Writer UI and Research → Writer briefs.

Provider order is controlled by AI_PROVIDER_ORDER. Free OpenRouter routes often pick a reasoning model: with the
old 512-token limit the whole budget went to reasoning and `content` came back
empty. We now allow enough tokens for reasoning + the post and retry once with
a larger budget if the reply was truncated.
"""
from __future__ import annotations

import httpx
import json
import re
from fastapi import HTTPException

from app.config import settings
from app.writer_prompt import build_writer_prompt

MAX_TOKENS = 1600
RETRY_MAX_TOKENS = 3200
OPENROUTER_TIMEOUT = httpx.Timeout(90.0, connect=15.0)
GEMINI_TIMEOUT = httpx.Timeout(25.0, connect=10.0)


def _extract_content(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return str(content).strip() if content else ""


def _truncated_by_reasoning(choice: dict, usage: dict | None = None) -> bool:
    usage = usage or {}
    details = usage.get("completion_tokens_details") or (
        choice.get("message", {}).get("usage", {}).get("completion_tokens_details") or {}
    )
    reasoning = details.get("reasoning_tokens", 0) or 0
    return choice.get("finish_reason") == "length" and reasoning > 0


async def _openrouter(prompt: str, token_multiplier: int = 1) -> tuple[str, list[str]]:
    errors: list[str] = []
    key = settings.openrouter_api_key
    if not key:
        return "", errors
    for max_tokens in (MAX_TOKENS * token_multiplier, RETRY_MAX_TOKENS * token_multiplier):
        try:
            async with httpx.AsyncClient(timeout=OPENROUTER_TIMEOUT) as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "http://localhost:8000",
                        "X-OpenRouter-Title": "JefroCrypto Threads Engine",
                    },
                    json={
                        "model": settings.openrouter_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens,
                        "temperature": 0.8,
                    },
                )
            if response.status_code >= 400:
                errors.append(f"OpenRouter HTTP {response.status_code}: {response.text[:200]}")
                break
            data = response.json()
            choice = data["choices"][0]
            text = _extract_content(choice.get("message", {}))
            if text:
                return text, errors
            if _truncated_by_reasoning(choice, data.get("usage")):
                errors.append(f"OpenRouter reasoning used all {max_tokens} tokens; retrying")
                continue
            errors.append("OpenRouter returned empty text")
            break
        except httpx.TimeoutException:
            errors.append("OpenRouter timeout")
            break
        except httpx.RequestError as exc:
            errors.append(f"OpenRouter connection: {type(exc).__name__}")
            break
        except (ValueError, KeyError, IndexError, TypeError):
            errors.append("OpenRouter returned an unexpected response")
            break
    return "", errors


async def _gemini(prompt: str, token_multiplier: int = 1, json_mode: bool = False) -> tuple[str, list[str]]:
    errors: list[str] = []
    key = settings.gemini_api_key
    if not key:
        return "", errors
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{settings.gemini_model}:generateContent"
    )
    try:
        async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT) as client:
            response = await client.post(
                url,
                params={"key": key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "maxOutputTokens": 1600 * token_multiplier,
                        "thinkingConfig": {"thinkingLevel": "low"},
                        **({"responseMimeType": "application/json"} if json_mode else {}),
                    },
                },
            )
        if response.status_code >= 400:
            errors.append(f"Gemini HTTP {response.status_code}: {response.text[:200]}")
            return "", errors
        data = response.json()
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict)).strip()
        if not text:
            errors.append("Gemini returned empty text")
        return text, errors
    except httpx.TimeoutException:
        errors.append("Gemini timeout")
    except httpx.RequestError as exc:
        errors.append(f"Gemini connection: {type(exc).__name__}")
    except (ValueError, KeyError, IndexError, TypeError):
        errors.append("Gemini returned an unexpected response")
    return "", errors


async def complete_prompt(prompt: str, *, token_multiplier: int = 1, json_mode: bool = False) -> tuple[str, str]:
    """Use enabled providers in configured order and return output with model id."""
    providers = {
        "openrouter": (settings.openrouter_api_key, settings.openrouter_model, _openrouter),
        "gemini": (settings.gemini_api_key, settings.gemini_model, _gemini),
    }
    if not any(pair[0] for pair in providers.values()):
        raise HTTPException(503, "Configure GEMINI_API_KEY or OPENROUTER_API_KEY")
    errors: list[str] = []
    order = list(dict.fromkeys([*settings.ai_provider_order, "openrouter", "gemini"]))
    for name in order:
        provider = providers.get(name)
        if not provider or not provider[0]:
            continue
        key, model, call = provider
        # Preserve a one-argument invocation for backwards compatibility/tests.
        if name == "gemini":
            result, errs = await call(prompt, token_multiplier, json_mode)
        elif token_multiplier == 1:
            result, errs = await call(prompt)
        else:
            result, errs = await call(prompt, token_multiplier)
        errors.extend(errs)
        if result and json_mode:
            candidate = re.sub(r"^```(?:json)?\s*", "", result.strip(), flags=re.I)
            candidate = candidate.rsplit("```", 1)[0].strip() if "```" in candidate else candidate
            try:
                parsed = json.loads(candidate[candidate.index("{"):candidate.rindex("}") + 1])
            except (ValueError, IndexError):
                errors.append(f"{name}: invalid JSON output")
                continue
            if not isinstance(parsed, dict) or not isinstance(parsed.get("variants"), list):
                errors.append(f"{name}: missing variants in JSON")
                continue
        if result:
            return result, f"{name}/{model}"
    raise HTTPException(502, "All AI providers failed: " + "; ".join(errors))


async def generate_text(
    *,
    topic: str,
    category: str = "Crypto Discussion",
    tone: str = "natural crypto native",
    language: str = "ru",
    structure: list[str] | None = None,
    examples: list[dict] | None = None,
    cta: str | None = None,
    style_limits: str | None = None,
    post_format: str | None = None,
) -> str:
    prompt = build_writer_prompt(
        topic=topic, category=category, tone=tone, language=language,
        structure=structure, examples=examples, cta=cta, style_limits=style_limits,
        post_format=post_format,
    )
    text, _model = await complete_prompt(prompt)
    return text
