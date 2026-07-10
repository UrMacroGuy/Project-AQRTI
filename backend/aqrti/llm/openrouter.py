"""
OpenRouter LLM client — thin httpx wrapper, OpenAI-compatible API.
Default model: nousresearch/hermes-3-llama-3.1-70b:free (Hermes 3 free tier).

Usage:
    from aqrti.llm.openrouter import ask, chat

    # One-shot prompt
    reply = ask("Summarise the Indian market outlook in 2 sentences.")

    # Multi-turn
    msgs = [{"role": "user", "content": "What is NIFTY?"}]
    reply = chat(msgs)
"""

from __future__ import annotations

import os
from typing import Optional

import httpx

from aqrti.utils.logger import get_logger

log = get_logger("openrouter")

_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
_API_KEY  = os.getenv("OPENROUTER_API_KEY", "")
_MODEL    = os.getenv("OPENROUTER_MODEL", "tencent/hy3:free")
_TIMEOUT  = 60.0  # seconds


def _headers() -> dict:
    if not _API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to backend/.env"
        )
    return {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://aqrti.local",
        "X-Title": "AQRTI Intelligence Terminal",
    }


def chat(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str:
    """
    Send a messages array and return the assistant reply as a string.
    Raises on HTTP error or missing API key.
    """
    payload = {
        "model":       model or _MODEL,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  max_tokens,
    }
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(
            f"{_BASE_URL}/chat/completions",
            headers=_headers(),
            json=payload,
        )
    resp.raise_for_status()
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise ValueError(f"Unexpected OpenRouter response shape: {data}") from exc


def ask(
    prompt: str,
    system: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str:
    """
    Convenience wrapper for a single user prompt.
    Optionally prepend a system message.
    """
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)


def is_configured() -> bool:
    """True if the API key env var is set (does not validate the key)."""
    return bool(_API_KEY)
