#!/usr/bin/env python3
"""Block Git from tracking files under directories/globs that must never be committed.

A `.gitignore` rule stops *accidental* staging, but it is silent if a file was force-added
(`git add -f`), added before the rule existed, or matched by a negation. This hook is the
positive assertion: given a committed list of forbidden path globs, it fails closed if any file
matching them is tracked in the Git index.

Config file (repository root), one gitignore-style glob per line, `#` comments allowed:

  .forbidden-paths

Examples:
  data/            # nothing under a top-level data/ directory may be tracked
  **/exports/      # no exports/ directory anywhere
  *.dcm            # no DICOM files by extension

Usage:
  python hooks/scripts/check_forbidden_paths.py
  python hooks/scripts/check_forbidden_paths.py --repo-root /path/to/repo

Pair with a `.gitignore` rule (staging convenience) and a push ruleset (server-side backstop).
Protect `.forbidden-paths` with CODEOWNERS. See policies/sensitive-data-scan-gates.md.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

FORBIDDEN_FILE = ".forbidden-paths"


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


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a gitignore-ish glob (``**``, ``*``, ``?``, trailing ``/``) to an anchored regex.

    A pattern with no leading ``/`` or ``**`` also matches at any directory depth, mirroring
    gitignore semantics for a bare name like ``exports/``.
    """
    anchored = pattern.startswith("/")
    prefix_dir = pattern.endswith("/")
    pattern = pattern.strip("/") if not anchored else pattern[1:].rstrip("/")
    out: list[str] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if pattern[i + 1 : i + 2] == "*":
                out.append(".*")
                i += 2
                if pattern[i : i + 1] == "/":
                    i += 1
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        i += 1
    body = "".join(out)
    lead = "" if anchored else r"(?:.*/)?"
    suffix = "(?:/.*)?" if prefix_dir else ""
    return re.compile(rf"^{lead}{body}{suffix}$")


def read_patterns(path: Path) -> list[str]:
    patterns: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def tracked_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        # Fail closed: an unreadable index must not look like "nothing is tracked".
        print(f"[forbidden-paths] ERROR cannot list tracked files: {exc}", file=sys.stderr)
        sys.exit(2)
    return [line for line in out.stdout.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)
    root = repo_root(args.repo_root)

    forbidden_path = root / FORBIDDEN_FILE
    if not forbidden_path.exists():
        return 0
    patterns = read_patterns(forbidden_path)
    if not patterns:
        return 0

    matchers = [(pattern, glob_to_regex(pattern)) for pattern in patterns]
    violations: list[tuple[str, str]] = []
    for path in tracked_files(root):
        if path == FORBIDDEN_FILE:
            continue
        for pattern, matcher in matchers:
            if matcher.match(path):
                violations.append((path, pattern))
                break

    if violations:
        for path, pattern in violations:
            print(
                f"[forbidden-paths] ERROR tracked file matches forbidden rule '{pattern}': {path}",
                file=sys.stderr,
            )
        print(
            "[forbidden-paths] Remove it from the index (git rm --cached <path>) and confirm it "
            "carries no sensitive data before deleting it from disk.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
