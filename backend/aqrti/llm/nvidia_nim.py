"""
NVIDIA NIM LLM client — thin httpx wrapper, OpenAI-compatible API.
Default model: meta/llama-3.1-8b-instruct.

Usage:
    from aqrti.llm.nvidia_nim import ask, chat

    # One-shot prompt
    reply = ask("Summarise the Indian market outlook in 2 sentences.")

    # Multi-turn
    msgs = [{"role": "user", "content": "What is NIFTY?"}]
    reply = chat(msgs)

Multi-key support (2026-07-15c): NVIDIA_NIM_API_KEY plus optional
NVIDIA_NIM_API_KEY_2..5 are pooled behind _KeyPool. Each key gets its own
40 RPM _RateLimiter (unchanged class/semantics) so N keys give N*40 RPM
headroom. A single-key deployment behaves identically to before this
change — the pool degenerates to one key, one limiter, no cooldown ever
triggered by anything but that one key's own 401/429s.
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
_MODEL      = os.getenv("NVIDIA_NIM_MODEL", "meta/llama-3.1-8b-instruct")
_TIMEOUT    = 60.0  # seconds
_RATE_LIMIT_RPM = int(os.getenv("NVIDIA_NIM_RATE_LIMIT_RPM", "40"))
_COOLDOWN_SECONDS = 60.0

# Collect NVIDIA_NIM_API_KEY + NVIDIA_NIM_API_KEY_2..5 (env-driven, no code
# change needed to add/remove a key — just set/unset the env var).
_API_KEYS: list[str] = [
    k for k in (
        os.getenv("NVIDIA_NIM_API_KEY", ""),
        os.getenv("NVIDIA_NIM_API_KEY_2", ""),
        os.getenv("NVIDIA_NIM_API_KEY_3", ""),
        os.getenv("NVIDIA_NIM_API_KEY_4", ""),
        os.getenv("NVIDIA_NIM_API_KEY_5", ""),
    ) if k
]


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

    def load(self) -> int:
        """Current calls in the trailing 60s window — used to pick the least-loaded key."""
        with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] >= 60.0:
                self._calls.popleft()
            return len(self._calls)


class _KeyPool:
    """
    Round-robins across configured API keys, picking the least-loaded one
    per call. A key that 401s/429s is marked cooling-down for
    _COOLDOWN_SECONDS and skipped by acquire() until it expires — with a
    single key, cooldown just means "wait like before" (no other key to
    fall back to), identical to pre-multi-key behavior.
    """

    def __init__(self, keys: list[str], rpm: int):
        self._keys = keys
        self._limiters = {k: _RateLimiter(rpm) for k in keys}
        self._cooldown_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def _available_keys(self) -> list[str]:
        now = time.monotonic()
        with self._lock:
            return [k for k in self._keys if self._cooldown_until.get(k, 0) <= now]

    def acquire(self) -> str:
        """Block (via the chosen key's limiter) and return the key to use."""
        if not self._keys:
            raise RuntimeError(
                "NVIDIA_NIM_API_KEY is not set. Add it to backend/.env"
            )
        available = self._available_keys() or self._keys   # all cooling down → use least-bad anyway
        key = min(available, key=lambda k: self._limiters[k].load())
        self._limiters[key].acquire()
        return key

    def mark_cooldown(self, key: str) -> None:
        with self._lock:
            self._cooldown_until[key] = time.monotonic() + _COOLDOWN_SECONDS
        log.warning("NVIDIA NIM key ...%s cooling down %ds after 401/429", key[-4:], _COOLDOWN_SECONDS)

    def key_count(self) -> int:
        return len(self._keys)


_pool = _KeyPool(_API_KEYS, _RATE_LIMIT_RPM)


def _headers(key: str) -> dict:
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _post(payload: dict, key: str) -> httpx.Response:
    with httpx.Client(timeout=_TIMEOUT) as client:
        return client.post(
            f"{_BASE_URL}/chat/completions",
            headers=_headers(key),
            json=payload,
        )


def chat(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str:
    """
    Send a messages array and return the assistant reply as a string.
    Raises on HTTP error or missing API key.

    On a 401/429 from the chosen key, marks it cooling-down and retries
    once on a different key (no-op if there's only one key configured —
    matches old single-key behavior exactly: the retry just fails the
    same way the original single call would have).
    """
    payload = {
        "model":       model or _MODEL,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  max_tokens,
    }
    key = _pool.acquire()
    resp = _post(payload, key)
    if resp.status_code in (401, 429) and _pool.key_count() > 1:
        _pool.mark_cooldown(key)
        retry_key = _pool.acquire()
        if retry_key != key:
            resp = _post(payload, retry_key)
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
    """True if at least one API key env var is set (does not validate the key)."""
    return bool(_API_KEYS)


def key_count() -> int:
    """Number of configured NVIDIA NIM API keys (for diagnostics/logging)."""
    return _pool.key_count()
