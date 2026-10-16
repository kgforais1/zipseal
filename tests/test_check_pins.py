"""The pin guard must fail closed: every matrix row behaves as specified."""

import importlib.util
from pathlib import Path

import pytest


def _load_guard():
    path = Path(__file__).resolve().parent.parent / "hooks" / "scripts" / "check_pins.py"
    spec = importlib.util.spec_from_file_location("check_pins", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_guard = _load_guard()
check_hook_revs = _guard.check_hook_revs
check_workflow = _guard.check_workflow
scan = _guard.scan
main = _guard.main

VALID_SHA = "3e8a8703264a2f4a69428a0aa4dcb512790b2c8c"
REPO = "https://github.com/x/y"
UV_SHA = "1c37ad07a6a961277cf70c0d37d6f313000f5884"


def _config(repo: str, rev_line: str | None) -> str:
    lines = ["repos:", f"  - repo: {repo}"]
    if rev_line is not None:
        lines.append(f"    rev: {rev_line}")
    lines.extend(["    hooks:", "      - id: a"])
    return "\n".join(lines) + "\n"


def _setup_uv(with_block: str) -> str:
    return (
        "jobs:\n"
        "  check:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"      - uses: astral-sh/setup-uv@{UV_SHA}\n"
        f"{with_block}"
    )


def _uses_step(uses: str) -> str:
    return f"jobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: {uses}\n"


EXACT = '        with:\n          version: "0.12.24"\n'

CONFIG_CASES = [
    ("valid hex with comment", _config(REPO, f"{VALID_SHA}  # v6.0.0"), False),
    ("tag rev", _config(REPO, "v8.30.0"), True),
    ("scp remote with tag rev", _config("git@example.com:x/y.git", "v1.0.0"), True),
    ("uppercase hex", _config(REPO, VALID_SHA.upper() + "  # v6"), True),
    ("short hex", _config(REPO, "3e8a8703  # short"), True),
    ("over-long hex", _config(REPO, VALID_SHA + "00  # long"), True),
    ("numeric rev", _config(REPO, "123"), True),
    (
        "mapping rev",
        "repos:\n  - repo: https://github.com/x/y\n    rev:\n      nested: true\n",
        True,
    ),
    ("local repo", "repos:\n  - repo: local\n    hooks:\n      - id: a\n", False),
    ("meta repo", "repos:\n  - repo: meta\n    hooks:\n      - id: a\n", False),
    ("remote repo with no rev key", _config(REPO, None), True),
    ("pinned rev with no comment", _config(REPO, VALID_SHA), True),
    ("rev without hooks key", f"repos:\n  - repo: {REPO}\n    rev: {VALID_SHA}  # v6\n", False),
    (
        "alias to valid hex",
        f".sha: &a {VALID_SHA}\nrepos:\n  - repo: {REPO}\n    rev: *a\n    hooks:\n      - id: a\n",
        False,
    ),
    (
        "alias to tag",
        f".tag: &t v1.0.0\nrepos:\n  - repo: {REPO}\n    rev: *t\n    hooks:\n      - id: a\n",
        True,
    ),
    (
        "undefined alias",
        f"repos:\n  - repo: {REPO}\n    rev: *nope\n    hooks:\n      - id: a\n",
        True,
    ),
    ("quoted sha with comment", _config(REPO, f'"{VALID_SHA}"  # v6'), False),
    ("quoted sha without comment", _config(REPO, f'"{VALID_SHA}"'), True),
    (
        "quoted key with comment",
        _config(REPO, f"{VALID_SHA}  # v6").replace("    rev:", '    "rev":'),
        False,
    ),
    (
        "quoted key without comment",
        _config(REPO, VALID_SHA).replace("    rev:", '    "rev":'),
        True,
    ),
    (
        "multiline value with comment",
        f"repos:\n  - repo: {REPO}\n    rev:\n      {VALID_SHA}  # v6\n    hooks:\n      - id: a\n",
        False,
    ),
    (
        "multiline value without comment",
        f"repos:\n  - repo: {REPO}\n    rev:\n      {VALID_SHA}\n    hooks:\n      - id: a\n",
        True,
    ),
]

WORKFLOW_CASES = [
    ("exact version", _setup_uv(EXACT), False),
    ("missing with block", _setup_uv(""), True),
    ("bare version key", _setup_uv("        with:\n          version:\n"), True),
    ("empty version", _setup_uv('        with:\n          version: ""\n'), True),
    ("latest", _setup_uv("        with:\n          version: latest\n"), True),
    ("latest-known", _setup_uv("        with:\n          version: latest-known\n"), True),
    ("range", _setup_uv('        with:\n          version: ">=0.12.10"\n'), True),
    ("pep440 range", _setup_uv('        with:\n          version: "~=0.12.10"\n'), True),
    ("wildcard", _setup_uv('        with:\n          version: "0.12.x"\n'), True),
    ("bare minor", _setup_uv('        with:\n          version: "0.12"\n'), True),
    ("float version", _setup_uv("        with:\n          version: 0.12\n"), True),
    (
        "expression version",
        _setup_uv('        with:\n          version: "${{ env.UV_VERSION }}"\n'),
        True,
    ),
    ("pinned uses", _uses_step(f"actions/checkout@{VALID_SHA}"), False),
    ("tag uses", _uses_step("actions/checkout@v7"), True),
    ("local uses", _uses_step("./local-action"), False),
    ("docker uses", _uses_step("docker://img:tag"), False),
    (
        "unrelated workflow",
        "jobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
        False,
    ),
]


@pytest.mark.parametrize(
    ("name", "content", "fails"), CONFIG_CASES, ids=[c[0] for c in CONFIG_CASES]
)
def test_hook_revs_matrix(tmp_path: Path, name: str, content: str, fails: bool) -> None:
    target = tmp_path / "config.yaml"
    target.write_text(content, encoding="utf-8")
    findings = check_hook_revs(target)
    assert bool(findings) is fails, findings


def test_hook_revs_crlf(tmp_path: Path) -> None:
    content = (
        (f"repos:\n  - repo: {REPO}\n    rev: {VALID_SHA}  # v6\n    hooks:\n      - id: a\n")
        .encode()
        .replace(b"\n", b"\r\n")
    )
    target = tmp_path / "config.yaml"
    target.write_bytes(content)
    assert check_hook_revs(target) == []


@pytest.mark.parametrize(
    ("name", "content", "fails"), WORKFLOW_CASES, ids=[c[0] for c in WORKFLOW_CASES]
)
def test_workflow_matrix(tmp_path: Path, name: str, content: str, fails: bool) -> None:
    target = tmp_path / "workflow.yml"
    target.write_text(content, encoding="utf-8")
    findings = check_workflow(target)
    assert bool(findings) is fails, findings


def test_scan_dispatches_on_filename(tmp_path: Path) -> None:
    dirty = _config(REPO, "v1.0.0")
    assert scan(tmp_path / "notes.txt") == []
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(dirty, encoding="utf-8")
    assert scan(config) != []
    assert scan(config.resolve()) != []


def test_main_exit_codes(tmp_path: Path, capsys) -> None:
    target = tmp_path / ".pre-commit-config.yaml"
    target.write_text(_config(REPO, f"{VALID_SHA}  # v6"), encoding="utf-8")
    assert main([str(target)]) == 0
    assert capsys.readouterr().err == ""
    target.write_text(_config(REPO, "v1.0.0"), encoding="utf-8")
    assert main([str(target)]) == 1
    assert capsys.readouterr().err != ""


def test_real_tree_is_clean() -> None:
    root = Path(__file__).resolve().parent.parent
    assert check_hook_revs(root / ".pre-commit-config.yaml") == []
    assert check_workflow(root / ".github" / "workflows" / "ci.yml") == []
    assert check_workflow(root / ".github" / "workflows" / "dependency-audit.yml") == []
