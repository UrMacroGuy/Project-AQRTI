"""
LLM provider selector — picks OpenRouter or NVIDIA NIM based on
AQRTI_LLM_PROVIDER (backend/.env), so callers don't need to know which
backend is live. Both clients share the same chat()/ask()/is_configured()
signatures, so this is a pure dispatch layer, no logic duplication.

Usage:
    from aqrti.llm.provider import ask, chat, active_provider
"""

from __future__ import annotations

import os
from typing import Optional

from aqrti.llm import nvidia_nim, openrouter
from aqrti.utils.logger import get_logger

log = get_logger("llm_provider")

_PROVIDERS = {
    "openrouter": openrouter,
    "nvidia_nim": nvidia_nim,
}


def active_provider() -> str:
    name = os.getenv("AQRTI_LLM_PROVIDER", "openrouter").strip().lower()
    return name if name in _PROVIDERS else "openrouter"


def _module():
    return _PROVIDERS[active_provider()]


def is_configured() -> bool:
    return _module().is_configured()


def chat(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str:
    mod = _module()
    if not mod.is_configured():
        raise RuntimeError(
            f"Active LLM provider '{active_provider()}' is not configured "
            f"(missing API key in backend/.env)."
        )
    return mod.chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)


def ask(
    prompt: str,
    system: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str:
    mod = _module()
    if not mod.is_configured():
        raise RuntimeError(
            f"Active LLM provider '{active_provider()}' is not configured "
            f"(missing API key in backend/.env)."
        )
    return mod.ask(prompt, system=system, model=model, temperature=temperature, max_tokens=max_tokens)
