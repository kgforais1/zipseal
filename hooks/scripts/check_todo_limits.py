#!/usr/bin/env python3
"""
check_todo_limits.py — pre-commit hook for living TODO / to_do backlog size.

Enforces soft/hard line caps on repo backlog files (see
dev-docs/README.md). Does not scan inline TODO comments in source;
the gardening pass in dev-docs/README.md covers those.

Usage:
  python hooks/scripts/check_todo_limits.py [file ...]

If no files are passed, checks TODO.md at the repo root.

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
# TODO.md at the repo root is the only living backlog (see dev-docs/README.md).
# The pre-commit `files:` filter matches the same single path.
BACKLOG_PATH = "TODO.md"


def is_backlog_path(path: Path) -> bool:
    return path.as_posix() == BACKLOG_PATH


def default_targets(repo_root: Path) -> list[Path]:
    # Return the repo-relative path, so is_backlog_path() accepts it.
    return [Path(BACKLOG_PATH)] if (repo_root / BACKLOG_PATH).is_file() else []


def check(filepath: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not filepath.exists():
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
            "Prune done items, or move large work into dev-docs/plans/."
        )
    elif lines > SOFT_LINE_CAP:
        warnings.append(
            f"{rel}: {lines} lines > soft cap {SOFT_LINE_CAP} "
            f"(hard cap {HARD_LINE_CAP}). Prune or promote items to dev-docs/plans/."
        )

    return errors, warnings


def main() -> int:
    repo_root = Path.cwd()
    args = [Path(a) for a in sys.argv[1:]]

    if args:
        files = [p for p in args if is_backlog_path(p)]
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
