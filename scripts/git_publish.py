"""
AQRTI Git Publish
=================
One-shot: stages all meaningful changes, commits with a smart message, pushes to GitHub.
Run it when you're done with a session. That's it.
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
GIT = r"C:\Program Files\Git\cmd\git.exe"

IGNORED_PATTERNS = {
    ".db-wal", ".db-shm", ".log", ".pyc",
    "__pycache__", ".DS_Store", "Thumbs.db",
}

def git(*args, check=False):
    return subprocess.run([GIT, *args], cwd=REPO_ROOT, capture_output=True, text=True, check=check)

def is_ignorable(path):
    return any(pat in path for pat in IGNORED_PATTERNS)

def get_changed_files():
    result = git("status", "--porcelain")
    files = []
    for line in result.stdout.splitlines():
        if len(line) < 3:
            continue
        path = line[3:].strip().strip('"')
        if not is_ignorable(path):
            files.append(path)
    return files

def smart_message(files):
    label_map = [
        ("ui/",                          "UI"),
        ("backend\\aqrti\\api",          "API routes"),
        ("backend/aqrti/api",            "API routes"),
        ("backend\\intelligence_training","Intelligence training"),
        ("backend/intelligence_training", "Intelligence training"),
        ("backend\\ml",                  "ML"),
        ("backend/ml",                   "ML"),
        ("backend\\paper_trading",       "Paper trading"),
        ("backend/paper_trading",        "Paper trading"),
        ("backend\\strategies",          "Strategies"),
        ("backend/strategies",           "Strategies"),
        ("backend\\agents",              "Research agents"),
        ("backend/agents",               "Research agents"),
        ("backend\\learning",            "Learning engine"),
        ("backend/learning",             "Learning engine"),
        ("backend\\sentiment",           "Sentiment"),
        ("backend/sentiment",            "Sentiment"),
        ("backend\\data_supremacy",      "Data supremacy"),
        ("backend/data_supremacy",       "Data supremacy"),
        ("backend\\",                    "Backend"),
        ("backend/",                     "Backend"),
        ("scripts\\",                    "Scripts"),
        ("scripts/",                     "Scripts"),
        ("plans\\",                      "Docs"),
        ("plans/",                       "Docs"),
    ]

    seen_labels = {}
    for f in files:
        matched = False
        for prefix, label in label_map:
            if f.startswith(prefix):
                seen_labels[label] = seen_labels.get(label, 0) + 1
                matched = True
                break
        if not matched:
            seen_labels["Root files"] = seen_labels.get("Root files", 0) + 1

    parts = [f"{label} ({n} file{'s' if n > 1 else ''})" for label, n in seen_labels.items()]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"[publish] {', '.join(parts)} — {ts}"

def main():
    print("AQRTI Git Publish")
    print("=" * 40)

    # Check for changes
    files = get_changed_files()
    if not files:
        print("Nothing to commit — working tree is clean.")
        input("\nPress Enter to close.")
        sys.exit(0)

    print(f"Found {len(files)} changed file(s):")
    for f in files[:20]:
        print(f"  + {f}")
    if len(files) > 20:
        print(f"  ... and {len(files) - 20} more")

    # Stage all changed files
    print("\nStaging files...")
    for f in files:
        git("add", f)
    # Always include these if modified
    for extra in ["README.md", "CHANGELOG.md"]:
        git("add", extra)

    staged = git("diff", "--cached", "--name-only")
    if not staged.stdout.strip():
        print("Nothing staged — all changes may already be committed.")
        input("\nPress Enter to close.")
        sys.exit(0)

    # Commit
    msg = smart_message(files)
    print(f"\nCommit message:\n  {msg}")
    commit = git("commit", "-m", msg)
    if commit.returncode != 0:
        print(f"\nCommit failed:\n{commit.stderr.strip()}")
        input("\nPress Enter to close.")
        sys.exit(1)
    print("Committed.")

    # Push
    print("\nPushing to GitHub (origin/main)...")
    push = git("push", "origin", "main")
    if push.returncode != 0:
        print(f"\nPush failed:\n{push.stderr.strip()}")
        input("\nPress Enter to close.")
        sys.exit(1)

    print("\nDone. All changes pushed to GitHub.")
    input("\nPress Enter to close.")

if __name__ == "__main__":
    main()
