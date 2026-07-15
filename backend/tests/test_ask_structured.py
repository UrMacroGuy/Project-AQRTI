"""
Live end-to-end test for aqrti.llm.provider.ask_structured().

This is NOT a mocked unit test — it makes a real call against whichever LLM
provider is configured in backend/.env (AQRTI_LLM_PROVIDER), because the
point of ask_structured() is fail-closed behavior against a REAL model's
real (sometimes messy) output, not against a hand-crafted string. Skips
cleanly if no provider is configured (e.g. CI with no API key) rather than
failing the whole suite.

Run from the backend directory:
  python -m pytest tests/test_ask_structured.py -v -s
"""

from __future__ import annotations

import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(_BACKEND) / ".env")

import pytest
from pydantic import BaseModel, Field

from aqrti.llm import provider as llm_provider


class CapitalAnswer(BaseModel):
    """Trivial 2-field schema used only to prove ask_structured() round-trips
    a real LLM response into a validated Pydantic object."""
    country: str = Field(description="The country name from the question, verbatim")
    capital: str = Field(description="The capital city of that country")


@pytest.mark.skipif(
    not llm_provider.is_configured(),
    reason="No LLM provider configured in backend/.env",
)
def test_ask_structured_live_call():
    result = llm_provider.ask_structured(
        prompt="What is the capital of France? Respond referring to the country as 'France'.",
        response_model=CapitalAnswer,
        max_tokens=200,
    )

    print(f"\n[test_ask_structured_live_call] provider={llm_provider.active_provider()!r}")
    print(f"[test_ask_structured_live_call] result={result!r}")

    assert result is not None, "ask_structured returned None — see logged raw response/validation error above"
    assert isinstance(result, CapitalAnswer)
    assert isinstance(result.country, str) and result.country.strip() != ""
    assert isinstance(result.capital, str) and result.capital.strip() != ""
    assert "paris" in result.capital.lower()


def test_ask_structured_fails_closed_on_garbage(monkeypatch):
    """Fail-closed check: if the provider returns text that can't validate
    against the schema, ask_structured must return None, never a guessed
    / partially-filled object."""
    monkeypatch.setattr(llm_provider, "ask", lambda *a, **k: "This is not JSON at all.")
    result = llm_provider.ask_structured(
        prompt="irrelevant — ask() is monkeypatched",
        response_model=CapitalAnswer,
    )
    assert result is None
