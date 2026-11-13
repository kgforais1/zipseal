"""Build the frozen zipseal-gui app for macOS, Windows and Linux.

`pyproject.toml`'s `build` dependency group provides PyInstaller, and this
module is the single entry point that resolves the version, checks the
interpreter and drives the freeze for one target (plan: GUI executables).

The interpreter is pinned to one python-build-standalone release. PyInstaller
has to resolve Tcl/Tk inside the extracted distribution, so freezing on
whatever interpreter happens to be on `PATH` - the project's `.python-version`
is 3.12 - would bundle a Tk tree the pin was never verified against.
"""

from __future__ import annotations

import argparse
import platform
import tomllib
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGING_DIR.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"

APP_NAME = "zipseal"
GUI_NAME = "zipseal-gui"

TARGETS = ("macos", "windows", "linux")

# python-build-standalone release 20261021 (published 2026-10-21), the newest
# CPython 3.13 `uv python install` offers. The assets are
# cpython-3.13.17+20261021-<triple>-install_only.tar.gz for
# aarch64-apple-darwin, x86_64-pc-windows-msvc and x86_64-unknown-linux-gnu.
# The macOS arm64 build imports Tcl/Tk 9.0. Windows and Linux Tk versions are
# measured when those builds run.
BUILD_PYTHON = "3.13.17"

VERSION_PLACEHOLDER = "@VERSION@"
VERSION_NUMBERS_PLACEHOLDER = "@VERSION_TUPLE@"

INFO_PLIST_TEMPLATE = {
    "CFBundleName": APP_NAME,
    "CFBundleDisplayName": APP_NAME,
    "CFBundleShortVersionString": VERSION_PLACEHOLDER,
    "CFBundleVersion": VERSION_PLACEHOLDER,
}


def read_version(path: Path = PYPROJECT) -> str:
    """Return the `version` declared in the repository's pyproject.toml."""
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    project = data.get("project")
    if not isinstance(project, dict):
        raise SystemExit(f"packaging/build.py: {path} has no [project] table")
    version = project.get("version")
    if not isinstance(version, str) or not version:
        raise SystemExit(f"packaging/build.py: {path} has no [project] version")
    return version


def version_tuple(version: str) -> str:
    """Render a version as the four numbers the Windows version resource wants."""
    parts = version.split(".")
    if not 1 <= len(parts) <= 4 or not all(part.isdigit() for part in parts):
        raise SystemExit(f"packaging/build.py: version {version!r} is not one to four numbers")
    numbers = [int(part) for part in parts]
    numbers.extend([0] * (4 - len(numbers)))
    return ", ".join(str(number) for number in numbers)


def substitute_version(template: str, version: str) -> str:
    """Fill a template's version placeholders: the version and its numbers."""
    filled = template.replace(VERSION_PLACEHOLDER, version)
    return filled.replace(VERSION_NUMBERS_PLACEHOLDER, version_tuple(version))


def render_info_plist(version: str) -> dict[str, str]:
    """Return the macOS Info.plist fields the `.spec` fills per version."""
    return {key: substitute_version(value, version) for key, value in INFO_PLIST_TEMPLATE.items()}


def render_windows_version_info(version: str) -> str:
    """Return the Windows version resource text with the version filled in."""
    template = (PACKAGING_DIR / "windows" / "version_info.txt").read_text(encoding="utf-8")
    return substitute_version(template, version)


def collect_data_files() -> list[tuple[str, str]]:
    """Return the `datas` tuples the `.spec` bundle beside the frozen modules.

    Both live under `_MEIPASS/zipseal/` next to `gui.ICON`: the SVG the window
    prefers, and the PNG `icons.py` generates as the fallback. The PNG does not
    exist until a build runs, so nothing here may require it.
    """
    return [
        ("src/zipseal/icon.svg", APP_NAME),
        ("build/icons/icon.png", APP_NAME),
    ]


def require_build_python() -> None:
    """Exit unless the running interpreter is the pinned build interpreter."""
    running = platform.python_version()
    if running != BUILD_PYTHON:
        raise SystemExit(
            f"packaging/build.py: expected the build interpreter Python "
            f"{BUILD_PYTHON} (python-build-standalone 20261021), found {running}; "
            f"run `uv python install {BUILD_PYTHON}` then "
            f"`uv run --python {BUILD_PYTHON} --group build python "
            f"packaging/build.py`, which also keeps `.python-version` (3.12) out "
            "of the freeze"
        )


def main(argv: list[str] | None = None) -> None:
    """Resolve the version and check the interpreter for one target.

    Exits non-zero: icon generation, the freeze and the post-build packaging
    steps are not implemented yet.
    """
    parser = argparse.ArgumentParser(
        prog="build.py",
        description="Freeze zipseal-gui for one platform (macOS, Windows, Linux).",
    )
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--skip-sign", action="store_true", help="leave signing to the sign job")
    parser.add_argument("--version", default=read_version())
    args = parser.parse_args(argv)
    require_build_python()
    raise SystemExit(
        "packaging/build.py: icon generation and freezing are not implemented yet "
        f"(target {args.target}, version {args.version})."
    )


if __name__ == "__main__":
    main()
