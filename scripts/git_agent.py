"""
AQRTI Git Agent
===============
Watches the project directory for significant file changes and automatically
commits + pushes them to GitHub (origin/main).

How it works:
  1. Every POLL_INTERVAL seconds, checks `git status` for modified/new files
  2. Ignores noisy files (db-wal, db-shm, logs, __pycache__, .pyc)
  3. Waits for QUIET_PERIOD seconds of no new changes before committing
     (so it batches all files from a coding session, not one file at a time)
  4. Generates a smart commit message from the changed file list
  5. git add → git commit → git push origin main

Run:
  python scripts/git_agent.py

Stop:
  Ctrl+C  (commits any pending changes before exiting)
"""

import subprocess
import time
import sys
import os
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
REPO_ROOT    = Path(__file__).parent.parent.resolve()
POLL_INTERVAL  = 30    # seconds between status checks
QUIET_PERIOD   = 120   # seconds of no new changes before auto-committing
MIN_FILES      = 1     # minimum changed files to trigger a commit
REMOTE         = "origin"
BRANCH         = "main"

# Files/patterns to never commit (in addition to .gitignore)
IGNORED_PATTERNS = {
    ".db-wal", ".db-shm", ".log", ".pyc",
    "__pycache__", ".DS_Store", "Thumbs.db",
}

GIT = r"C:\Program Files\Git\cmd\git.exe"

# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: list[str], check=True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=REPO_ROOT,
        capture_output=True, text=True,
        check=check,
    )

def git(*args, check=True) -> subprocess.CompletedProcess:
    return run([GIT, *args], check=check)

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def is_ignorable(path: str) -> bool:
    for pat in IGNORED_PATTERNS:
        if pat in path:
            return True
    return False

def get_changed_files() -> list[str]:
    """Return list of changed/untracked files that aren't ignored."""
    result = git("status", "--porcelain")
    files = []
    for line in result.stdout.splitlines():
        if len(line) < 3:
            continue
        status = line[:2].strip()
        path   = line[3:].strip().strip('"')
        if status == "??" or status:
            if not is_ignorable(path):
                files.append(path)
    return files

def smart_commit_message(files: list[str]) -> str:
    """Generate a meaningful commit message from the changed file list."""
    categories = {
        "ui": [],
        "backend/aqrti/api": [],
        "backend/intelligence_training": [],
        "backend/ml": [],
        "backend/paper_trading": [],
        "backend/strategies": [],
        "backend/agents": [],
        "backend/learning": [],
        "backend/sentiment": [],
        "backend/data_supremacy": [],
        "backend": [],
        "scripts": [],
        "plans": [],
        "root": [],
    }

    for f in files:
        matched = False
        for cat in categories:
            if cat == "root":
                continue
            if f.startswith(cat + "/") or f.startswith(cat + "\\"):
                categories[cat].append(f)
                matched = True
                break
        if not matched:
            categories["root"].append(f)

    parts = []
    label_map = {
        "ui":                         "UI",
        "backend/aqrti/api":          "API routes",
        "backend/intelligence_training": "Intelligence training",
        "backend/ml":                 "ML",
        "backend/paper_trading":      "Paper trading",
        "backend/strategies":         "Strategies",
        "backend/agents":             "Research agents",
        "backend/learning":           "Learning engine",
        "backend/sentiment":          "Sentiment engine",
        "backend/data_supremacy":     "Data supremacy",
        "backend":                    "Backend",
        "scripts":                    "Scripts",
        "plans":                      "Docs/plans",
        "root":                       "Project root",
    }

    for cat, label in label_map.items():
        if categories[cat]:
            n = len(categories[cat])
            parts.append(f"{label} ({n} file{'s' if n > 1 else ''})")

    summary = ", ".join(parts) if parts else f"{len(files)} files"
    ts      = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"[auto] Update {summary} — {ts}"

def stage_and_commit(files: list[str]) -> bool:
    """Stage changed files, commit, push. Returns True on success."""
    # Stage only the changed files (not git add -A)
    for f in files:
        git("add", f, check=False)

    # Also stage README.md and CHANGELOG.md if they exist and changed
    for extra in ["README.md", "CHANGELOG.md"]:
        git("add", extra, check=False)

    # Check if there's actually anything staged
    staged = git("diff", "--cached", "--name-only")
    if not staged.stdout.strip():
        log("Nothing staged after add — skipping commit")
        return False

    msg = smart_commit_message(files)
    log(f"Committing: {msg}")

    commit = git("commit", "-m", msg, check=False)
    if commit.returncode != 0:
        log(f"Commit failed: {commit.stderr.strip()}")
        return False

    log(f"Pushing to {REMOTE}/{BRANCH}...")
    push = git("push", REMOTE, BRANCH, check=False)
    if push.returncode != 0:
        log(f"Push failed: {push.stderr.strip()}")
        log("Will retry on next cycle.")
        return False

    log(f"Pushed successfully. Files: {', '.join(files[:5])}{'...' if len(files) > 5 else ''}")
    return True

# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    log(f"AQRTI Git Agent started — watching: {REPO_ROOT}")
    log(f"Poll: {POLL_INTERVAL}s | Quiet period: {QUIET_PERIOD}s before commit")
    log("Press Ctrl+C to stop (commits pending changes before exit)")

    last_change_time = None
    known_files: set[str] = set()

    # Seed known_files so first run doesn't commit stale diff
    try:
        initial = get_changed_files()
        known_files = set(initial)
        if initial:
            log(f"Existing uncommitted files detected ({len(initial)}): will commit after quiet period")
            last_change_time = time.time()
    except Exception as e:
        log(f"Init error: {e}")

    try:
        while True:
            time.sleep(POLL_INTERVAL)

            try:
                changed = get_changed_files()
            except Exception as e:
                log(f"git status error: {e}")
                continue

            current_set = set(changed)

            if current_set != known_files:
                new_files = current_set - known_files
                gone_files = known_files - current_set
                if new_files:
                    log(f"New changes detected: {', '.join(list(new_files)[:4])}")
                known_files = current_set
                last_change_time = time.time()

            # Commit if we have files and quiet period has elapsed
            if (
                last_change_time is not None
                and len(known_files) >= MIN_FILES
                and (time.time() - last_change_time) >= QUIET_PERIOD
            ):
                files = list(known_files)
                success = stage_and_commit(files)
                if success:
                    known_files = set()
                    last_change_time = None
                else:
                    # Reset timer to retry after another quiet period
                    last_change_time = time.time()

            elif last_change_time and known_files:
                remaining = QUIET_PERIOD - (time.time() - last_change_time)
                if remaining > 0:
                    log(f"Waiting for quiet period... {int(remaining)}s remaining ({len(known_files)} file(s) pending)")

    except KeyboardInterrupt:
        log("Stopping agent...")
        if known_files:
            log(f"Committing {len(known_files)} pending file(s) before exit...")
            stage_and_commit(list(known_files))
        log("Agent stopped.")
        sys.exit(0)

if __name__ == "__main__":
    main()
