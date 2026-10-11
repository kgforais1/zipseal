"""The core the CLI and the GUI share (dev-docs/plans/2026-10-10-gui.md)."""

import io
from pathlib import Path

import pytest
from helpers import extract, make_tree

from zipseal import cli
from zipseal.errors import EXIT_OK, UsageError, WriteError
from zipseal.job import run_job
from zipseal.options import DEFAULT_EXCLUDES, Options
from zipseal.passwords import Password

WEAK = "test-short"


def inputs(tmp_path: Path) -> Path:
    make_tree(tmp_path, {"in/a.txt": "hello\n", "in/sub/b.txt": "world\n"})
    return tmp_path / "in"


def test_options_defaults_match_the_cli() -> None:
    command = cli.parse_args(["in", "-o", "x.zip"])
    assert command.options == Options(paths=[Path("in")], output=Path("x.zip"))
    assert command.options.level == 6
    assert command.options.order == "path"
    assert command.options.default_excludes
    assert DEFAULT_EXCLUDES == (".DS_Store", "._*", "Thumbs.db")


def test_run_job_rejects_an_empty_password(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    options = Options(paths=[inputs(tmp_path)], output=out / "b.zip")
    warn = io.StringIO()
    with pytest.raises(UsageError, match="the password is empty"):
        run_job(options, lambda _: Password(""), warn=warn)
    assert not (out / "b.zip").exists()
    assert not warn.getvalue()


def test_run_job_strength_warning_goes_to_the_warn_sink(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    options = Options(paths=[inputs(tmp_path)], output=out / "b.zip")
    warn = io.StringIO()
    assert run_job(options, lambda _: Password(WEAK), warn=warn) == EXIT_OK
    assert "shorter than 12" in warn.getvalue()
    assert WEAK not in warn.getvalue() and WEAK not in capsys.readouterr().out
    assert extract(out / "b.zip", WEAK)["in/a.txt"] == b"hello\n"


def test_run_job_dry_run_asks_for_no_password(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    asked: list[bool] = []
    out = tmp_path / "b.zip"
    options = Options(paths=[inputs(tmp_path)], output=out, dry_run=True)

    def get_password(_: Options) -> Password:
        asked.append(True)
        return Password("test-password-long")

    assert run_job(options, get_password, warn=io.StringIO()) == EXIT_OK
    assert asked == []
    assert not out.exists()
    assert "entries," in capsys.readouterr().out


def test_run_job_asks_for_a_password_after_preflight(tmp_path: Path) -> None:
    """An existing output fails before the prompt, as the CLI always has."""
    out = tmp_path / "b.zip"
    out.write_text("precious")
    options = Options(paths=[inputs(tmp_path)], output=out)
    asked: list[bool] = []

    def get_password(_: Options) -> Password:
        asked.append(True)
        return Password("test-password-long")

    with pytest.raises(WriteError, match="already exist"):
        run_job(options, get_password, warn=io.StringIO())
    assert asked == []
    assert out.read_text() == "precious"
