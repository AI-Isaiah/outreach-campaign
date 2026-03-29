"""Shared LLM client — multi-provider abstraction for Claude, OpenAI, and Gemini.

Provider priority (uses first available API key):
  1. ANTHROPIC_API_KEY  → Claude Haiku
  2. OPENAI_API_KEY     → GPT-4o-mini
  3. GEMINI_API_KEY     → Gemini 2.0 Flash
"""

from __future__ import annotations

import json
import logging
import os
import re

import httpx

from src.constants import LLM_MODELS

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ANTHROPIC = LLM_MODELS["default_anthropic"]
DEFAULT_MODEL_OPENAI = "gpt-4o-mini"
DEFAULT_MODEL_GEMINI = "gemini-2.0-flash"


def _call_anthropic(prompt: str, api_key: str, *, model: str = DEFAULT_MODEL_ANTHROPIC,
                    max_tokens: int = 2000, timeout: float = 30.0) -> str:
    """Call Anthropic Messages API and return the raw text response."""
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def _call_openai(prompt: str, api_key: str, *, model: str = DEFAULT_MODEL_OPENAI,
                 max_tokens: int = 2000, timeout: float = 30.0) -> str:
    """Call OpenAI Chat Completions API and return the raw text response."""
    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


_gemini_key_warned = False


def _call_gemini(prompt: str, api_key: str, *, model: str = DEFAULT_MODEL_GEMINI,
                 max_tokens: int = 2000, timeout: float = 30.0) -> str:
    """Call Google Gemini API and return the raw text response."""
    global _gemini_key_warned
    if not _gemini_key_warned:
        logger.warning("Gemini API key passed as URL parameter (Google API design limitation)")
        _gemini_key_warned = True
    # NOTE: Google's Generative Language API requires the key as a URL query parameter.
    # There is no Authorization header option — this is a Google API design limitation,
    # not an implementation choice. The google-generativeai SDK uses the same mechanism.
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    try:
        resp = httpx.post(
            url,
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # Redact API key from error message to prevent log exposure
        safe_msg = str(exc).replace(api_key, "REDACTED")
        raise httpx.HTTPStatusError(safe_msg, request=exc.request, response=exc.response) from None
    except httpx.HTTPError as exc:
        safe_msg = str(exc).replace(api_key, "REDACTED")
        raise type(exc)(safe_msg) from None
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def detect_provider() -> tuple[str, str] | None:
    """Detect which LLM API key is available. Returns (provider_name, api_key) or None."""
    for env_var, name in [
        ("ANTHROPIC_API_KEY", "anthropic"),
        ("OPENAI_API_KEY", "openai"),
        ("GEMINI_API_KEY", "gemini"),
    ]:
        key = os.getenv(env_var, "").strip()
        if key:
            return (name, key)
    return None


def call_llm(prompt: str, *, max_tokens: int = 2000, timeout: float = 30.0) -> tuple[str, str]:
    """Call the first available LLM provider. Returns (raw_text, provider_name).

    Raises RuntimeError if no API key is configured.
    """
    provider = detect_provider()
    if not provider:
        raise RuntimeError("No LLM API key configured (set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY)")

    name, api_key = provider
    callers = {
        "anthropic": _call_anthropic,
        "openai": _call_openai,
        "gemini": _call_gemini,
    }
    raw_text = callers[name](prompt, api_key, max_tokens=max_tokens, timeout=timeout)
    return raw_text, name


def call_llm_safe(prompt: str, *, max_tokens: int = 2000, timeout: float = 30.0,
                  fallback: str = "") -> tuple[str, str | None]:
    """Call LLM with graceful error handling. Returns (text, provider_name_or_None).

    Never raises — returns fallback on any error.
    """
    try:
        return call_llm(prompt, max_tokens=max_tokens, timeout=timeout)
    except RuntimeError as exc:
        logger.warning("No LLM provider available: %s", exc)
        return fallback, None
    except httpx.HTTPStatusError as exc:
        logger.warning("LLM API HTTP error: %s %s", exc.response.status_code, exc.response.text[:200])
        return fallback, None
    except httpx.TimeoutException:
        logger.warning("LLM API call timed out (%.0fs)", timeout)
        return fallback, None
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError, OSError) as exc:
        logger.exception("Unexpected error during LLM call: %s", exc)
        return fallback, None


def strip_markdown_fences(text: str) -> str:
    """Strip markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text
