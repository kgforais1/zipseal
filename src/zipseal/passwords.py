"""Password sources (SPEC.md §4). No code path may print, log or raise a password.

`Password` hides its value from repr() and str(), so it cannot leak through a
traceback, a debug print or an f-string by accident. Read `.value` explicitly.
"""

import getpass
import os
import secrets
import stat
import string
import sys
import warnings
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TextIO

from zipseal.errors import UsageError

GENERATED_LENGTH = 24
GENERATED_ALPHABET = string.ascii_letters + string.digits
SHORT_PASSWORD = 12


class Password:
    __slots__ = ("generated", "value")

    def __init__(self, value: str, *, generated: bool = False) -> None:
        self.value = value
        self.generated = generated

    def __repr__(self) -> str:
        return "Password(<hidden>)"

    __str__ = __repr__

    def encode(self) -> bytes:
        return self.value.encode("utf-8")


def generate() -> Password:
    value = "".join(secrets.choice(GENERATED_ALPHABET) for _ in range(GENERATED_LENGTH))
    return Password(value, generated=True)


def from_prompt(
    *,
    isatty: Callable[[], bool] | None = None,
    prompt: Callable[[str], str] = getpass.getpass,
) -> Password:
    """Ask twice without echo. Refuse to fall back to visible input."""
    if not (isatty or sys.stdin.isatty)():
        raise UsageError(
            "no terminal to prompt for a password; use --password-env or --password-file"
        )
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            first = prompt("Password: ")
            second = prompt("Confirm password: ")
        except getpass.GetPassWarning:
            raise UsageError(
                "this terminal cannot hide password input; use --password-env or --password-file"
            ) from None
    if first != second:
        raise UsageError("passwords do not match")
    return Password(first)


def from_env(name: str, environ: Mapping[str, str] | None = None) -> Password:
    value = (os.environ if environ is None else environ).get(name)
    if not value:
        raise UsageError(f"environment variable {name} is unset or empty")
    return Password(value)


def from_file(path: Path, warn: TextIO | None = None) -> Password:
    """Read the first line, without its line ending. Warn if others can read the file."""
    warn = warn or sys.stderr
    try:
        mode = path.stat().st_mode
        with path.open(encoding="utf-8", newline="") as fh:
            line = fh.readline()
    except (OSError, UnicodeDecodeError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) else "not valid UTF-8"
        raise UsageError(f"cannot read password file {path}: {reason}") from None
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        print(
            f"zipseal: warning: password file {path} is readable by other users; "
            "consider chmod 600",
            file=warn,
        )
    value = line.removesuffix("\n").removesuffix("\r")
    if not value:
        raise UsageError(f"password file {path} has an empty first line")
    return Password(value)


def check_strength(password: Password, warn: TextIO | None = None) -> None:
    """Reject empty passwords. Warn about short or non-ASCII ones."""
    warn = warn or sys.stderr
    if not password.value:
        raise UsageError("the password is empty")
    if password.generated:
        return
    if len(password.value) < SHORT_PASSWORD:
        print(
            f"zipseal: warning: the password is shorter than {SHORT_PASSWORD} characters; "
            "AE-2 key derivation is weak, so prefer --generate-password",
            file=warn,
        )
    if not password.value.isascii():
        print(
            "zipseal: warning: the password has non-ASCII characters; "
            "some unzip tools may not open the archive",
            file=warn,
        )
