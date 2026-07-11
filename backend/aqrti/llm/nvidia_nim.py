"""
NVIDIA NIM LLM client — thin httpx wrapper, OpenAI-compatible API.
Default model: z-ai/glm-5.2.

Usage:
    from aqrti.llm.nvidia_nim import ask, chat

    # One-shot prompt
    reply = ask("Summarise the Indian market outlook in 2 sentences.")

    # Multi-turn
    msgs = [{"role": "user", "content": "What is NIFTY?"}]
    reply = chat(msgs)
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Optional

import httpx

from aqrti.utils.logger import get_logger

log = get_logger("nvidia_nim")

_BASE_URL   = os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
_API_KEY    = os.getenv("NVIDIA_NIM_API_KEY", "")
_MODEL      = os.getenv("NVIDIA_NIM_MODEL", "z-ai/glm-5.2")
_TIMEOUT    = 60.0  # seconds
_RATE_LIMIT_RPM = int(os.getenv("NVIDIA_NIM_RATE_LIMIT_RPM", "40"))


class _RateLimiter:
    """Sliding-window limiter: blocks so at most N calls happen per 60s."""

    def __init__(self, max_per_minute: int):
        self._max = max_per_minute
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] >= 60.0:
                self._calls.popleft()
            if len(self._calls) >= self._max:
                wait = 60.0 - (now - self._calls[0])
                if wait > 0:
                    log.info(f"NVIDIA NIM rate limit ({self._max}/min) reached, waiting {wait:.1f}s")
                    time.sleep(wait)
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= 60.0:
                    self._calls.popleft()
            self._calls.append(time.monotonic())


_limiter = _RateLimiter(_RATE_LIMIT_RPM)


def _headers() -> dict:
    if not _API_KEY:
        raise RuntimeError(
            "NVIDIA_NIM_API_KEY is not set. Add it to backend/.env"
        )
    return {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
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
    _limiter.acquire()
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
        raise ValueError(f"Unexpected NVIDIA NIM response shape: {data}") from exc


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
