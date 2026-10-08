#!/usr/bin/env python3
"""
check_file_size.py — pre-commit hook enforcing policies/file-size-and-counts.md.

Usage (pre-commit wires this automatically):
  python hooks/scripts/check_file_size.py [file ...]

Exit codes: 0 = pass (warnings printed but not blocking), 1 = hard violation.

Thresholds are read from environment variables so CI can tighten them without
editing this file:
  POLICY_SOFT_LINE_CAP      (default 600)
  POLICY_HARD_LINE_CAP      (default 1000)
  POLICY_MAX_BYTES          (default 512000 = 500 KB)
  POLICY_BINARY_HARD_BYTES  (default 5242880 = 5 MB)
  POLICY_DOC_SOFT_LINE_CAP  (default 1000)
  POLICY_WARN_AS_ERROR      (set to 1 to treat soft warnings as hard errors)
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# ── Thresholds ────────────────────────────────────────────────────────────────
SOFT_LINE_CAP = int(os.getenv("POLICY_SOFT_LINE_CAP", "600"))
HARD_LINE_CAP = int(os.getenv("POLICY_HARD_LINE_CAP", "1000"))
MAX_BYTES = int(os.getenv("POLICY_MAX_BYTES", str(500 * 1024)))
BINARY_HARD_BYTES = int(os.getenv("POLICY_BINARY_HARD_BYTES", str(5 * 1024 * 1024)))
DOC_SOFT_LINE_CAP = int(os.getenv("POLICY_DOC_SOFT_LINE_CAP", "1000"))
WARN_AS_ERROR = os.getenv("POLICY_WARN_AS_ERROR", "0") == "1"

# ── Extension sets ────────────────────────────────────────────────────────────
SOURCE_EXTS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".rs",
    ".go",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".scala",
    ".cs",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
}
DOC_EXTS = {".md", ".rst", ".txt"}

# ── Inline override marker ────────────────────────────────────────────────────
# Add near the top of a file to raise its cap:
#   # policy:file-size allow=600 reason=<why>
OVERRIDE_RE = re.compile(r"policy:file-size\s+allow=(\d+)", re.IGNORECASE)

# ── Ignored path fragments ────────────────────────────────────────────────────
IGNORE_FRAGMENTS = [
    "notes_and_ideas/",
    ".context/",
    "node_modules/",
    "__pycache__/",
    ".git/",
    "migrations/",
    "vendor/",
    "dist/",
    "build/",
    ".venv/",
    "venv/",
    ".tox/",
    ".eggs/",
]


def is_ignored(path: str) -> bool:
    return any(frag in path.replace(os.sep, "/") for frag in IGNORE_FRAGMENTS)


def read_override(path: Path) -> int | None:
    """Return per-file line-cap override if the policy marker is present."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for i, line in enumerate(fh):
                if i >= 12:
                    break
                m = OVERRIDE_RE.search(line)
                if m:
                    return int(m.group(1))
    except OSError:
        pass
    return None


def check(filepath: str) -> tuple[list[str], list[str]]:
    """Return (hard_errors, soft_warnings) for one file."""
    errors: list[str] = []
    warnings: list[str] = []

    path = Path(filepath)
    if not path.exists() or is_ignored(filepath):
        return errors, warnings

    size = path.stat().st_size
    ext = path.suffix.lower()

    # ── Binary / giant file ───────────────────────────────────────────────────
    if size > BINARY_HARD_BYTES:
        mb = size / (1024 * 1024)
        limit_mb = BINARY_HARD_BYTES / (1024 * 1024)
        errors.append(
            f"{filepath}: {mb:.1f} MB exceeds {limit_mb:.0f} MB hard limit. "
            "Use Git LFS or release assets for large files."
        )
        return errors, warnings  # no point checking lines

    if size > MAX_BYTES and ext not in SOURCE_EXTS | DOC_EXTS:
        kb = size / 1024
        limit_kb = MAX_BYTES / 1024
        errors.append(
            f"{filepath}: {kb:.0f} KB exceeds {limit_kb:.0f} KB limit for non-source files."
        )

    # ── Line count ────────────────────────────────────────────────────────────
    if ext in SOURCE_EXTS | DOC_EXTS:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return errors, warnings

        lines = content.count("\n")
        override = read_override(path)

        if ext in DOC_EXTS:
            soft_cap = override or DOC_SOFT_LINE_CAP
            hard_cap = override or (DOC_SOFT_LINE_CAP * 2)
        else:
            soft_cap = override or SOFT_LINE_CAP
            hard_cap = override or HARD_LINE_CAP

        if lines > hard_cap:
            errors.append(
                f"{filepath}: {lines} lines > hard cap {hard_cap}. "
                "Split by responsibility, or add: "
                f"# policy:file-size allow={lines + 50} reason=<why>"
            )
        elif lines > soft_cap:
            warnings.append(
                f"{filepath}: {lines} lines > soft cap {soft_cap} (hard cap {hard_cap})."
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
        print(f"[file-size] WARN  {w}", file=sys.stderr)
    for e in all_errors:
        print(f"[file-size] ERROR {e}", file=sys.stderr)

    if all_errors:
        return 1
    if WARN_AS_ERROR and all_warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
