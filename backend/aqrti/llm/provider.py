"""
LLM provider selector — picks OpenRouter or NVIDIA NIM based on
AQRTI_LLM_PROVIDER (backend/.env), so callers don't need to know which
backend is live. Both clients share the same chat()/ask()/is_configured()
signatures, so this is a pure dispatch layer, no logic duplication.

Usage:
    from aqrti.llm.provider import ask, chat, active_provider
"""

from __future__ import annotations

import json
import os
from typing import Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from aqrti.llm import nvidia_nim, openrouter
from aqrti.llm.json_utils import strip_code_fences
from aqrti.utils.logger import get_logger

log = get_logger("llm_provider")

ModelT = TypeVar("ModelT", bound=BaseModel)

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


def ask_structured(
    prompt: str,
    response_model: Type[ModelT],
    system: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Optional[ModelT]:
    """
    Structured-output variant of ask(): appends response_model's JSON schema
    to the prompt, calls the active provider, and parses+validates the raw
    text into an instance of response_model via Pydantic.

    Fail-closed by design (CLAUDE.md: no fabricated data, ever): on ANY
    failure — provider not configured, LLM call raises, response isn't valid
    JSON, or JSON doesn't satisfy response_model's schema — this returns None.
    It never constructs a partial or guessed instance of response_model to
    paper over a bad response. Callers must treat None as "no result", not
    retry-with-defaults.

    The raw LLM response and the parse/validation error are logged (not
    raised) so a caller can inspect why a call failed without the helper
    itself throwing on the common "model didn't cooperate" case. Genuine
    programming errors (missing config) still raise via the underlying ask().
    """
    schema = response_model.model_json_schema()
    structured_prompt = f"""{prompt}

Respond with STRICT JSON ONLY (no markdown code fences, no prose before or \
after) matching exactly this JSON schema:
{json.dumps(schema, indent=2)}

Output valid JSON only — it must parse and validate against the schema above."""

    kwargs: dict = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    try:
        raw_text = ask(structured_prompt, system=system, model=model, **kwargs)
    except Exception as exc:
        log.warning("ask_structured: LLM call failed for %s: %s", response_model.__name__, exc)
        return None

    cleaned = strip_code_fences(raw_text)

    try:
        return response_model.model_validate_json(cleaned)
    except (ValidationError, json.JSONDecodeError, ValueError) as exc:
        log.warning(
            "ask_structured: response failed to validate against %s: %s | raw=%r",
            response_model.__name__, exc, raw_text[:500],
        )
        return None
