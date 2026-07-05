"""
Obsidian Vault Writer — shared upsert/ownership primitives.
Spec: docs/OBSIDIAN_INTEGRATION_PLAN.md §5.

The vault is a derived view of the DB: every note is deterministically
rendered from DB state, so a write is safe to skip if the rendered bytes
are unchanged, and must never clobber a file that isn't ours.
"""
from __future__ import annotations

from pathlib import Path


OWNERSHIP_MARKER = "aqrti_generated: true"


class OwnershipConflict(Exception):
    """Raised when a target path exists but lacks the aqrti_generated marker."""


def is_aqrti_owned(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        head = path.read_text(encoding="utf-8")[:1000]
    except Exception:
        return False
    return OWNERSHIP_MARKER in head


def upsert_note(path: Path, content: str) -> str:
    """
    Write `content` to `path` if it differs from what's already there.
    Returns one of: "written", "unchanged", "skipped_collision".
    Never deletes, never overwrites a non-aqrti file.
    """
    if not is_aqrti_owned(path):
        return "skipped_collision"

    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except Exception:
            existing = None
        if existing == content:
            return "unchanged"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return "written"


def wikilink(name: str) -> str:
    return f"[[{name}]]"
