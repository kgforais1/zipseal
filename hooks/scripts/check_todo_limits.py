#!/usr/bin/env python3
"""
check_todo_limits.py — pre-commit hook for living TODO / to_do backlog size.

Enforces soft/hard line caps on repo backlog files (see
dev-docs/README.md). Does not scan inline TODO comments in source;
the gardening pass in dev-docs/README.md covers those.

Usage:
  python hooks/scripts/check_todo_limits.py [file ...]

If no files are passed, scans the default backlog filenames at repo root and
under plans/ (non-archive).

Exit codes: 0 = pass (warnings OK), 1 = hard violation.

Environment:
  POLICY_TODO_SOFT_LINE_CAP   (default 150)
  POLICY_TODO_HARD_LINE_CAP   (default 300)
  POLICY_WARN_AS_ERROR        (set to 1 to treat soft warnings as errors)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SOFT_LINE_CAP = int(os.getenv("POLICY_TODO_SOFT_LINE_CAP", "150"))
HARD_LINE_CAP = int(os.getenv("POLICY_TODO_HARD_LINE_CAP", "300"))
WARN_AS_ERROR = os.getenv("POLICY_WARN_AS_ERROR", "0") == "1"

# Basenames treated as living backlog files when present in the commit set
# or when scanning defaults.
BACKLOG_BASENAMES = {
    "to_do.md",
    "todo.md",
    "TODO.md",
    "TO_DO.md",
    "backlog.md",
}

IGNORE_FRAGMENTS = [
    ".context/",
    "dev-docs/plans/archive/",
    "node_modules/",
    ".git/",
    "backups/",
]


def is_ignored(path: str) -> bool:
    normalized = path.replace(os.sep, "/")
    return any(frag in normalized for frag in IGNORE_FRAGMENTS)


def is_backlog_path(path: Path) -> bool:
    name = path.name
    if name in BACKLOG_BASENAMES:
        return True
    # Allow to_do.md under plans/ but not archived plans content
    if path.suffix.lower() == ".md" and name.lower() in {"to_do.md", "todo.md"}:
        return True
    return False


def default_targets(repo_root: Path) -> list[Path]:
    candidates = [
        repo_root / "to_do.md",
        repo_root / "TODO.md",
        repo_root / "todo.md",
        repo_root / "backlog.md",
        repo_root / "plans" / "to_do.md",
        repo_root / "plans" / "TODO.md",
    ]
    return [p for p in candidates if p.is_file()]


def check(filepath: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not filepath.exists() or is_ignored(str(filepath)):
        return errors, warnings
    if not is_backlog_path(filepath):
        return errors, warnings

    try:
        text = filepath.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        errors.append(f"{filepath}: cannot read ({exc})")
        return errors, warnings

    lines = text.count("\n") + (0 if text.endswith("\n") or text == "" else 1)
    rel = str(filepath)

    if lines > HARD_LINE_CAP:
        errors.append(
            f"{rel}: {lines} lines > hard cap {HARD_LINE_CAP} for living TODO/backlog. "
            "Prune done items, move large work into plans/, or split the backlog."
        )
    elif lines > SOFT_LINE_CAP:
        warnings.append(
            f"{rel}: {lines} lines > soft cap {SOFT_LINE_CAP} "
            f"(hard cap {HARD_LINE_CAP}). Prune or promote items to plans/."
        )

    return errors, warnings


def main() -> int:
    repo_root = Path.cwd()
    args = [Path(a) for a in sys.argv[1:]]

    if args:
        files = [p for p in args if is_backlog_path(p) and not is_ignored(str(p))]
        # If pre-commit passed only non-backlog files, nothing to do
        if not files and args:
            return 0
    else:
        files = default_targets(repo_root)

    all_errors: list[str] = []
    all_warnings: list[str] = []
    for f in files:
        errs, warns = check(f)
        all_errors.extend(errs)
        all_warnings.extend(warns)

    for w in all_warnings:
        print(f"[todo-limits] WARN  {w}", file=sys.stderr)
    for e in all_errors:
        print(f"[todo-limits] ERROR {e}", file=sys.stderr)

    if all_errors:
        return 1
    if WARN_AS_ERROR and all_warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
