#!/usr/bin/env python3
"""Block commits that contain personal data in text: home-folder paths and email addresses.

Usage (pre-commit passes staged files):
  python3 hooks/scripts/check_personal_data.py FILE...

Allowed: GitHub noreply addresses, example.com/example.org addresses,
noreply@anthropic.com (used in Co-Authored-By trailers), and the
placeholder home paths /Users/you and /home/you. A line can opt out with the
comment `personal-data:allow` plus a reason. Exit 1 on any finding.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HOME_PATH = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\\\?Users\\\\?)(?!you\b)([A-Za-z0-9._-]+)")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ALLOWED_EMAIL = re.compile(
    r"(@users\.noreply\.github\.com|@example\.(com|org)|^noreply@anthropic\.com)$"
)
OPT_OUT = "personal-data:allow"
SKIP = {"uv.lock"}


def scan(path: Path) -> list[str]:
    if path.name in SKIP:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []  # binary files are handled by .forbidden-paths
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        if OPT_OUT in line:
            continue
        for match in HOME_PATH.finditer(line):
            findings.append(f"{path}:{number}: home-folder path {match.group(0)!r}")
        for match in EMAIL.finditer(line):
            if not ALLOWED_EMAIL.search(match.group(0)):
                findings.append(f"{path}:{number}: email address {match.group(0)!r}")
    return findings


def main(argv: list[str]) -> int:
    findings = [f for name in argv for f in scan(Path(name))]
    for finding in findings:
        print(f"[personal-data] {finding}", file=sys.stderr)
    if findings:
        print(
            "[personal-data] Remove it, use a placeholder such as /Users/you, or add "
            f"'{OPT_OUT}: <reason>' on the line.",
            file=sys.stderr,
        )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
