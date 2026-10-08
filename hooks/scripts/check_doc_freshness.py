#!/usr/bin/env python3
"""
check_doc_freshness.py — pre-commit hook enforcing the doc gardening rules in dev-docs/README.md.

Checks that markdown docs in policy-required paths carry a valid
"Last reviewed: YYYY-MM-DD" marker that is not past the staleness window.

Usage (pre-commit wires this automatically):
  python hooks/scripts/check_doc_freshness.py [file ...]

Exit codes: 0 = pass, 1 = hard violation (missing marker in required path,
or doc is hard-stale). Soft warnings are printed but do not block.

Environment variables:
  POLICY_FRESHNESS_WARN_DAYS   days before soft warning (default 180)
  POLICY_FRESHNESS_HARD_DAYS   days before hard block  (default 365)
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date
from pathlib import Path

# ── Staleness windows ─────────────────────────────────────────────────────────
WARN_DAYS = int(os.getenv("POLICY_FRESHNESS_WARN_DAYS", "180"))
HARD_DAYS = int(os.getenv("POLICY_FRESHNESS_HARD_DAYS", "365"))

# ── Paths that MUST carry the marker ─────────────────────────────────────────
REQUIRED_DIRS: set[str] = {"user-docs"}
ROOT_REQUIRED: set[str] = {"README.md", "AGENTS.md", "SPEC.md", "TODO.md"}
REQUIRED_FILES: set[str] = {"dev-docs/README.md"}

# ── Exempt path fragments ─────────────────────────────────────────────────────
# Exemptions match whole path segments or leading path prefixes, never substrings,
# so "src/rebuild/x.md" or "user-docs/CHANGELOG-notes.md" are not exempt by accident.
EXEMPT_DIRS = {".context", "node_modules", "vendor", "dist", "build"}
EXEMPT_PREFIXES = ("dev-docs/plans/", "dev-docs/investigations/")
EXEMPT_ROOT_FILES = {"CHANGELOG.md", "CHANGELOG.dev.md"}

# Capture the whole value on the marker line, so "2026-10-08garbage" is rejected
# rather than matched by its valid prefix.
MARKER_RE = re.compile(r"Last reviewed:[ \t]*(\S*)[ \t]*$", re.IGNORECASE | re.MULTILINE)
TODAY = date.today()


def is_exempt(filepath: str) -> bool:
    path = Path(filepath)
    norm = path.as_posix()
    if norm in EXEMPT_ROOT_FILES:
        return True
    if norm.startswith(EXEMPT_PREFIXES):
        return True
    return bool(EXEMPT_DIRS & set(path.parts[:-1]))


def is_required(path: Path) -> bool:
    if path.suffix.lower() != ".md":
        return False
    norm_parts = set(path.parts)
    # Root-level docs
    if path.name in ROOT_REQUIRED and len(path.parts) == 1:
        return True
    if path.as_posix() in REQUIRED_FILES:
        return True
    # Docs inside required directories
    return bool(REQUIRED_DIRS & norm_parts)


def check(filepath: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not filepath.endswith(".md") or is_exempt(filepath):
        return errors, warnings

    path = Path(filepath)
    if not path.exists():
        return errors, warnings

    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return errors, warnings

    match = MARKER_RE.search(text)

    if not match:
        if is_required(path):
            errors.append(
                f"{filepath}: missing 'Last reviewed: YYYY-MM-DD' marker. "
                "Required in README.md, AGENTS.md, SPEC.md, TODO.md, user-docs/ "
                "and dev-docs/README.md."
            )
        return errors, warnings

    try:
        reviewed = date.fromisoformat(match.group(1))
    except ValueError:
        errors.append(f"{filepath}: unparseable date '{match.group(1)}' in Last reviewed marker.")
        return errors, warnings

    age = (TODAY - reviewed).days

    if age < 0:
        errors.append(f"{filepath}: Last reviewed {reviewed} is in the future.")
        return errors, warnings

    if age > HARD_DAYS:
        errors.append(
            f"{filepath}: Last reviewed {reviewed} ({age} days ago) "
            f"exceeds hard limit of {HARD_DAYS} days. "
            "Re-read, verify accuracy, and update the date."
        )
    elif age > WARN_DAYS:
        warnings.append(
            f"{filepath}: Last reviewed {reviewed} ({age} days ago) "
            f"exceeds soft limit of {WARN_DAYS} days. Review when convenient."
        )

    return errors, warnings


def main() -> int:
    files = sys.argv[1:]
    if not files:
        return 0

    all_errors: list[str] = []
    all_warnings: list[str] = []

    for f in files:
        errs, warns = check(f)
        all_errors.extend(errs)
        all_warnings.extend(warns)

    for w in all_warnings:
        print(f"[doc-freshness] WARN  {w}", file=sys.stderr)
    for e in all_errors:
        print(f"[doc-freshness] ERROR {e}", file=sys.stderr)

    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())
