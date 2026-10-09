#!/usr/bin/env python3
"""Block a commit that drops a protected entry from .gitignore.

On a sensitive-data repository the most dangerous single-line change is silently deleting a
`.gitignore` rule that was keeping a data/export/log directory out of Git. This hook makes those
rules non-optional: it reads a committed allowlist of patterns that MUST remain ignored and fails
closed if any of them is missing from `.gitignore`.

Config file (repository root), one pattern per line, `#` comments allowed:

  .gitignore-protected

Each non-comment line must appear verbatim as a line in `.gitignore`. The check is a whole-line
match, so a protected `data/` is not satisfied by an unrelated `mydata/`.

Usage:
  python hooks/scripts/check_gitignore_protected.py
  python hooks/scripts/check_gitignore_protected.py --repo-root /path/to/repo

Protect `.gitignore-protected` and `.gitignore` with CODEOWNERS so removing a protected rule
requires the security owner's review. See policies/sensitive-data-scan-gates.md.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROTECTED_FILE = ".gitignore-protected"
GITIGNORE_FILE = ".gitignore"


def repo_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(out.stdout.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fail closed: outside a git work tree this gate cannot vouch for anything.
        print("[gate] ERROR not inside a git repository (or git is missing)", file=sys.stderr)
        sys.exit(2)


def read_patterns(path: Path) -> list[str]:
    patterns: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)
    root = repo_root(args.repo_root)

    protected_path = root / PROTECTED_FILE
    if not protected_path.exists():
        # No protected list configured; nothing to enforce.
        return 0

    required = read_patterns(protected_path)
    if not required:
        return 0

    gitignore_path = root / GITIGNORE_FILE
    if not gitignore_path.exists():
        print(
            f"[gitignore-protected] ERROR {GITIGNORE_FILE} is missing but "
            f"{PROTECTED_FILE} requires {len(required)} pattern(s).",
            file=sys.stderr,
        )
        return 1

    present = {line.strip() for line in gitignore_path.read_text(encoding="utf-8").splitlines()}
    missing = [pattern for pattern in required if pattern not in present]
    if missing:
        for pattern in missing:
            print(
                f"[gitignore-protected] ERROR protected rule removed from "
                f"{GITIGNORE_FILE}: {pattern}",
                file=sys.stderr,
            )
        print(
            "[gitignore-protected] Restore the rule, or remove it from "
            f"{PROTECTED_FILE} with a reviewed, CODEOWNER-approved change.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
