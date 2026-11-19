"""The package version must match pyproject.toml and reach `--version`."""

import sys
import tomllib
from pathlib import Path

import pytest

import zipseal
from zipseal import cli

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return project["project"]["version"]


def test_package_version_matches_pyproject() -> None:
    assert zipseal.__version__ == _pyproject_version()


def test_cli_version_prints_the_package_version(capsys, monkeypatch) -> None:
    # argparse's version action uses sys.argv[0] as the program name, which
    # under pytest is the test runner, not the console script.
    monkeypatch.setattr(sys, "argv", ["zipseal"])
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"zipseal {zipseal.__version__}"
