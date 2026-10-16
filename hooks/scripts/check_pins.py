#!/usr/bin/env python3
"""Block version pins that can float at run time.

Usage (pre-commit passes matching staged files):
  uv run python hooks/scripts/check_pins.py FILE...

Three rules (see dev-docs/plans/2026-10-15-sha-pin-ci-tooling.md, Task 3):

1. Hook revs: in `.pre-commit-config.yaml`, every `repo:` except `local` and
   `meta` must pin a full 40-character lowercase hex SHA, and each pinned
   `rev` must carry its release tag as a trailing comment. The comment check
   is a raw-line pass because `yaml.safe_load` discards comments.
2. uv versions: in every workflow, each `astral-sh/setup-uv` step must set
   `with.version` to a full literal release version.
3. Action refs: in every workflow, each `uses:` naming a remote action must
   pin a full 40-character lowercase hex SHA. Local (`./…`) and `docker://…`
   refs are skipped.

Exit 1 on any finding.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

SHA = re.compile(r"[0-9a-f]{40}")
FULL_SHA = re.compile(r"\A[0-9a-f]{40}\Z")
EXACT_VERSION = re.compile(r"\d+\.\d+\.\d+")
REV_LINE = re.compile(r"^\s*rev:\s*([0-9a-f]{40})\b")
COMMENT = re.compile(r"#[ \t]*\S")
USES_SHA = re.compile(r"\A[^@\s]+@[0-9a-f]{40}\Z")

SKIP_REPOS = {"local", "meta"}


def _load(path: Path) -> tuple[object, list[str]]:
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, [f"{path}: cannot read file: {exc}"]
    try:
        return yaml.safe_load(text), []
    except yaml.YAMLError as exc:
        return None, [f"{path}: malformed YAML: {exc}"]


def check_hook_revs(path: Path) -> list[str]:
    findings: list[str] = []
    data, errors = _load(path)
    if errors:
        return errors
    repos = data.get("repos") if isinstance(data, dict) else None
    if not isinstance(repos, list):
        return [f"{path}: no `repos:` list found"]
    for entry in repos:
        if not isinstance(entry, dict):
            return [f"{path}: malformed repo entry: {entry!r}"]
        repo = entry.get("repo")
        if repo in SKIP_REPOS:
            continue
        rev = entry.get("rev")
        if not isinstance(rev, str) or not FULL_SHA.match(rev):
            findings.append(f"{path}: repo {repo!r} rev must be a 40-char hex SHA")
    # Comment check is a raw-line pass: safe_load discards comments, and
    # alias rev lines carry no literal hex so the pattern skips them.
    # splitlines() handles \n, \r\n and lone \r alike.
    try:
        lines = path.read_bytes().decode("utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{path}: cannot read file: {exc}"]
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith("#"):
            continue
        if REV_LINE.search(line) and not COMMENT.search(line.split("rev:", 1)[1]):
            findings.append(f"{path}:{number}: pinned rev carries no tag comment")
    return findings


def _iter_steps(data: object) -> list[tuple[dict, str]]:
    """Yield (step, where) for every step and every reusable-workflow job."""
    found: list[tuple[dict, str]] = []
    if not isinstance(data, dict):
        return found
    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        return found
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        if isinstance(job.get("uses"), str):
            found.append((job, f"job {job_name!r}"))
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for index, step in enumerate(steps):
            if isinstance(step, dict):
                found.append((step, f"job {job_name!r} step {index}"))
    return found


def check_workflow(path: Path) -> list[str]:
    findings: list[str] = []
    data, errors = _load(path)
    if errors:
        return errors
    for node, where in _iter_steps(data):
        uses = node.get("uses")
        if not isinstance(uses, str):
            continue
        if uses.startswith("./") or uses.startswith("docker://"):
            continue
        if not USES_SHA.match(uses):
            findings.append(f"{path}: {where} uses must pin a 40-char hex SHA")
        if "astral-sh/setup-uv" not in uses:
            continue
        with_block = node.get("with")
        version = with_block.get("version") if isinstance(with_block, dict) else None
        if not isinstance(version, str) or not EXACT_VERSION.fullmatch(version):
            findings.append(f"{path}: {where} setup-uv version must be an exact x.y.z release")
    return findings


def scan(path: Path) -> list[str]:
    posix = path.as_posix()
    if posix == ".pre-commit-config.yaml":
        return check_hook_revs(path)
    if ".github/workflows/" in posix:
        return check_workflow(path)
    return []


def main(argv: list[str]) -> int:
    findings = [f for name in argv for f in scan(Path(name))]
    for finding in findings:
        print(f"[pins] {finding}", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
