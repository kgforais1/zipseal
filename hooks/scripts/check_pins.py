#!/usr/bin/env python3
"""Block version pins that can float at run time.

Usage (pre-commit passes matching staged files):
  uv run python hooks/scripts/check_pins.py FILE...

Three rules (see dev-docs/plans/2026-10-15-sha-pin-ci-tooling.md, Task 3):

1. Hook revs: in `.pre-commit-config.yaml`, every `repo:` except `local` and
   `meta` must pin a full 40-character lowercase hex SHA, and each pinned
   `rev` must carry its release tag as a trailing comment. Comment positions
   come from `yaml.compose` marks, since parsing discards comments; alias use
   is detected at the key position and exempted because pre-commit resolves
   it identically.
2. uv versions: in every workflow, each `astral-sh/setup-uv` step must set
   `with.version` to a full literal release version. The action name is matched
   case-insensitively, since GitHub resolves owner/repo that way.
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
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

FULL_SHA = re.compile(r"\A[0-9a-f]{40}\Z")
EXACT_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
COMMENT = re.compile(r"#[ \t]*\S")
USES_SHA = re.compile(r"\A[^@\s]+@[0-9a-f]{40}\Z")

SKIP_REPOS = {"local", "meta"}
# GitHub resolves owner/repo case-insensitively, so a re-cased reference
# still runs setup-uv and must still pin an exact version.
SETUP_UV = "astral-sh/setup-uv"


def _read_text(path: Path) -> tuple[str | None, list[str]]:
    try:
        return path.read_bytes().decode("utf-8"), []
    except (OSError, UnicodeDecodeError) as exc:
        return None, [f"{path}: cannot read file: {exc}"]


def _parse(path: Path, text: str) -> tuple[object, list[str]]:
    try:
        return yaml.safe_load(text), []
    except yaml.YAMLError as exc:
        return None, [f"{path}: malformed YAML: {exc}"]


def check_hook_revs(path: Path) -> list[str]:
    findings: list[str] = []
    text, errors = _read_text(path)
    if errors or text is None:
        return errors
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        return [f"{path}: malformed YAML: {exc}"]
    lines = text.splitlines()
    # splitlines() handles \n, \r\n and lone \r alike, so mark columns,
    # which count from the start of the visual line, stay aligned.
    repos: object = None
    if isinstance(root, MappingNode):
        for key, value in root.value:
            if isinstance(key, ScalarNode) and key.value == "repos":
                repos = value
    if not isinstance(repos, SequenceNode):
        return [f"{path}: no `repos:` list found"]
    for entry in repos.value:
        if not isinstance(entry, MappingNode):
            return [f"{path}: malformed repo entry: {entry!r}"]
        fields: dict[str, tuple[object, object]] = {}
        for key, value in entry.value:
            if isinstance(key, ScalarNode):
                fields[key.value] = (key, value)
        repo_node = fields.get("repo", (None, None))[1]
        repo = repo_node.value if isinstance(repo_node, ScalarNode) else None
        if repo in SKIP_REPOS:
            continue
        rev_key, rev_val = fields.get("rev", (None, None))
        if not isinstance(rev_val, ScalarNode) or not FULL_SHA.match(rev_val.value):
            findings.append(f"{path}: repo {repo!r} rev must be a 40-char hex SHA")
            continue
        # Comment check on the rev scalar's own source position: safe_load
        # and compose both discard comments, so the raw line where the scalar
        # ends must carry the tag. Key position (not value) reveals alias use,
        # because compose resolves `rev: *anchor` to the anchored node.
        if isinstance(rev_key, ScalarNode):
            after = lines[rev_key.start_mark.line][rev_key.end_mark.column :]
            after = after.lstrip()
            if after.startswith(":"):
                after = after[1:].lstrip()
                if after.startswith("*"):
                    continue  # alias use: pre-commit resolves it identically
        end = rev_val.end_mark
        tail = lines[end.line][end.column :]
        if not COMMENT.search(tail):
            findings.append(f"{path}:{end.line + 1}: pinned rev carries no tag comment")
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
    text, errors = _read_text(path)
    if errors or text is None:
        return errors
    data, errors = _parse(path, text)
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
        if uses.rsplit("@", 1)[0].lower() != SETUP_UV:
            continue
        with_block = node.get("with")
        version = with_block.get("version") if isinstance(with_block, dict) else None
        if not isinstance(version, str) or not EXACT_VERSION.fullmatch(version):
            findings.append(f"{path}: {where} setup-uv version must be an exact x.y.z release")
    return findings


def scan(path: Path) -> list[str]:
    if path.name == ".pre-commit-config.yaml":
        return check_hook_revs(path)
    if ".github/workflows/" in path.as_posix():
        return check_workflow(path)
    return []


def main(argv: list[str]) -> int:
    findings = [f for name in argv for f in scan(Path(name))]
    for finding in findings:
        print(f"[pins] {finding}", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
