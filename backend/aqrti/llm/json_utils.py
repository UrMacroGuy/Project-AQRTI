"""
Shared JSON-cleanup helpers for LLM response parsing.

Extracted from intelligence/research_synthesizer.py so structured-output
callers (aqrti/llm/provider.py::ask_structured) and the research synthesizer's
hand-rolled dict parsing can both use one implementation instead of two
copies drifting apart.
"""

from __future__ import annotations


def strip_code_fences(text: str) -> str:
    """Defensively strip a leading/trailing ``` or ```json markdown fence that
    LLMs sometimes wrap "STRICT JSON ONLY" responses in despite instructions
    not to. Returns the input stripped of surrounding whitespace if there's no
    fence to remove."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t
