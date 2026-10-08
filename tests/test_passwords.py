import getpass
import io
import os
import warnings
from pathlib import Path

import pytest

from zipseal import cli, passwords
from zipseal.errors import EXIT_USAGE, UsageError

SECRET = "correct-horse-battery-staple"


def test_password_repr_hides_value() -> None:
    p = passwords.Password(SECRET)
    assert SECRET not in repr(p)
    assert SECRET not in str(p)
    assert SECRET not in f"{p}"
    assert p.encode() == SECRET.encode()


def test_generate() -> None:
    p = passwords.generate()
    assert p.generated
    assert len(p.value) == 24
    assert p.value.isascii() and p.value.isalnum()
    assert passwords.generate().value != p.value


def test_prompt_matching() -> None:
    answers = iter([SECRET, SECRET])
    p = passwords.from_prompt(isatty=lambda: True, prompt=lambda _: next(answers))
    assert p.value == SECRET and not p.generated


def test_prompt_mismatch() -> None:
    answers = iter([SECRET, SECRET + "x"])
    with pytest.raises(UsageError, match="do not match"):
        passwords.from_prompt(isatty=lambda: True, prompt=lambda _: next(answers))


def test_prompt_needs_tty() -> None:
    with pytest.raises(UsageError, match="no terminal"):
        passwords.from_prompt(isatty=lambda: False, prompt=lambda _: SECRET)


def test_prompt_refuses_echo_fallback() -> None:
    calls: list[str] = []

    def echoing_prompt(text: str) -> str:
        calls.append(text)
        warnings.warn("Can not control echo", getpass.GetPassWarning, stacklevel=1)
        return SECRET  # pragma: no cover - the warning is raised as an error first

    with pytest.raises(UsageError, match="cannot hide"):
        passwords.from_prompt(isatty=lambda: True, prompt=echoing_prompt)
    assert calls == ["Password: "]


def test_env() -> None:
    assert passwords.from_env("PW", {"PW": SECRET}).value == SECRET
    with pytest.raises(UsageError, match="unset or empty"):
        passwords.from_env("PW", {})
    with pytest.raises(UsageError, match="unset or empty"):
        passwords.from_env("PW", {"PW": ""})


@pytest.mark.parametrize("ending", ["", "\n", "\r\n", "\nsecond line\n"])
def test_file_first_line(tmp_path: Path, ending: str) -> None:
    f = tmp_path / "pw"
    f.write_bytes((SECRET + ending).encode())
    f.chmod(0o600)
    warn = io.StringIO()
    assert passwords.from_file(f, warn).value == SECRET
    assert warn.getvalue() == ""


def test_file_keeps_trailing_spaces(tmp_path: Path) -> None:
    f = tmp_path / "pw"
    f.write_text(SECRET + "  \n")
    f.chmod(0o600)
    assert passwords.from_file(f).value == SECRET + "  "


def test_file_readable_by_others_warns(tmp_path: Path) -> None:
    f = tmp_path / "pw"
    f.write_text(SECRET)
    f.chmod(0o644)
    warn = io.StringIO()
    passwords.from_file(f, warn)
    assert "readable by other users" in warn.getvalue()
    assert SECRET not in warn.getvalue()


def test_file_empty_first_line(tmp_path: Path) -> None:
    f = tmp_path / "pw"
    f.write_text("\n" + SECRET)
    with pytest.raises(UsageError, match="empty first line"):
        passwords.from_file(f)


def test_file_missing(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="cannot read"):
        passwords.from_file(tmp_path / "nope")


def test_strength_warnings() -> None:
    with pytest.raises(UsageError):
        passwords.check_strength(passwords.Password(""))
    warn = io.StringIO()
    passwords.check_strength(passwords.Password("short"), warn)
    assert "shorter than 12" in warn.getvalue()
    warn = io.StringIO()
    passwords.check_strength(passwords.Password("päßwörd-long-enough"), warn)
    assert "non-ASCII" in warn.getvalue()
    warn = io.StringIO()
    passwords.check_strength(passwords.Password(SECRET), warn)
    assert warn.getvalue() == ""


def test_cli_never_prints_supplied_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ZS_PW", SECRET)
    code = cli.main([str(tmp_path), "-o", str(tmp_path / "out.zip"), "--password-env", "ZS_PW"])
    out, err = capsys.readouterr()
    assert code != 0  # writing is not implemented yet; this path must still be clean
    assert SECRET not in out and SECRET not in err


def test_cli_failure_never_prints_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "pw"
    f.write_text(SECRET)
    os.chmod(f, 0o644)
    code = cli.main([str(tmp_path), "-o", "x.zip", "--password-file", str(f), "--level", "11"])
    out, err = capsys.readouterr()
    assert code == EXIT_USAGE
    assert SECRET not in out and SECRET not in err


def test_cli_usage_errors_exit_1(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["a"]) == EXIT_USAGE  # missing -o
    assert cli.main(["a", "-o", "x.zip", "--max-size", "25XB"]) == EXIT_USAGE
    assert (
        cli.main(["a", "-o", "x.zip", "--password-env", "A", "--generate-password"]) == EXIT_USAGE
    )
    assert "zipseal: error:" in capsys.readouterr().err


def test_cli_excludes() -> None:
    args = cli.parse_args(["a", "-o", "x.zip", "--exclude", "*.tmp"])
    assert args.excludes == [".DS_Store", "._*", "Thumbs.db", "*.tmp"]
    args = cli.parse_args(["a", "-o", "x.zip", "--no-default-excludes", "--exclude", "*.tmp"])
    assert args.excludes == ["*.tmp"]
