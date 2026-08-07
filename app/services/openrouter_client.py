# app/services/openrouter_client.py
"""
Thin client for the AI Manager's free-text chat, via OpenRouter (OpenAI-
compatible chat completions API, model chosen at deploy time).

Mirrors app/services/supabase_client.py's pattern: module-level functions,
no class, env vars read fresh via os.environ.get per call, a fresh
httpx.AsyncClient per call, fails open (returns None) on any HTTP error or
unexpected response shape so a down/misconfigured OpenRouter key degrades
ai_manager's reply (falls back to a templated message) instead of breaking
the chat endpoint.

Configured via OPENROUTER_API_KEY and OPENROUTER_MODEL (the exact model
slug as OpenRouter lists it, e.g. "google/gemini-3.5-flash-lite").
"""

import logging
import os
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = 30.0
_URL = "https://openrouter.ai/api/v1/chat/completions"


def is_configured() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY")) and bool(os.environ.get("OPENROUTER_MODEL"))


async def chat_completion(messages: list[dict[str, str]], temperature: float = 0.2) -> Optional[str]:
    """
    POST to OpenRouter's chat completions endpoint. Returns the assistant's
    raw text content, or None on any missing configuration / HTTP failure /
    unexpected response shape — callers must handle a None result (e.g. by
    falling back to a templated reply) rather than assuming a real answer.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    model = os.environ.get("OPENROUTER_MODEL", "")
    if not (api_key and model):
        log.info("OpenRouter not configured (OPENROUTER_API_KEY/OPENROUTER_MODEL) — skipping chat completion")
        return None

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": temperature}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(_URL, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
            return body["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
        log.warning("OpenRouter chat completion failed: %s", exc)
        return None
