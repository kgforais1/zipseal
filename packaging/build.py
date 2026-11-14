"""Build the frozen zipseal-gui app for macOS, Windows and Linux.

`pyproject.toml`'s `build` dependency group provides PyInstaller, and this
module is the single entry point that resolves the version, checks the
interpreter, generates the icons and drives the freeze for one target (plan:
GUI executables).

The interpreter is pinned to one python-build-standalone release. PyInstaller
has to resolve Tcl/Tk inside the extracted distribution, so freezing on
whatever interpreter happens to be on `PATH` - the project's `.python-version`
is 3.12 - would bundle a Tk tree the pin was never verified against.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

PACKAGING_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGING_DIR.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
SPEC_PATH = PACKAGING_DIR / "zipseal-gui.spec"
DIST_ROOT = REPO_ROOT / "dist"
PYINSTALLER_WORK = REPO_ROOT / "build" / "pyinstaller"

# The spec is exec'd by PyInstaller, so the target and version reach it through
# the environment this script sets: an argument cannot, and the spec must not
# have to be rendered into a temporary file.
BUILD_TARGET_ENV = "ZIPSEAL_BUILD_TARGET"
BUILD_VERSION_ENV = "ZIPSEAL_BUILD_VERSION"

APP_NAME = "zipseal"
GUI_NAME = "zipseal-gui"

TARGETS = ("macos", "windows", "linux")

# icons.host_key() reports platform.system().lower(): darwin, windows, linux.
# The build targets use macos for Darwin. PyInstaller freezes the host OS, so
# a different --target would label that host binary as another platform.
_HOST_TARGETS = {"darwin": "macos", "windows": "windows", "linux": "linux"}

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


def load_icons() -> ModuleType:
    """Load `packaging/icons.py` by path, the way the tests load this module.

    Neither file is a package member and `packaging/` must never sit on
    `sys.path`: it would shadow the PyPI `packaging` distribution for anything
    in this process that imports it.
    """
    path = PACKAGING_DIR / "icons.py"
    spec = importlib.util.spec_from_file_location("packaging_icons", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"packaging/build.py: cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def host_target() -> str:
    """Return the `--target` name for the machine running this build.

    The system name comes from `icons.host_key`, which is how the pinned
    resvg asset is chosen. `darwin` is the `macos` target.
    """
    system, _machine = load_icons().host_key()
    try:
        return _HOST_TARGETS[system]
    except KeyError:
        raise SystemExit(f"packaging/build.py: no build target for this host ({system})") from None


def require_host_target(target: str) -> None:
    """Exit when `--target` is not the platform PyInstaller would freeze."""
    host = host_target()
    if target != host:
        raise SystemExit(
            f"packaging/build.py: --target {target} does not match this build "
            f"host ({host}); PyInstaller freezes only the platform it runs on"
        )


def tk_preflight() -> None:
    """Exit unless the build interpreter's own Tcl/Tk can open a Tk root.

    A freeze bundles whatever Tcl/Tk the running interpreter resolves. If that
    is the host machine's tree rather than the extracted python-build-standalone
    one, the app breaks on a user's machine; fail here instead. `sys.base_prefix`
    is the managed interpreter even when the build runs inside a `uv` venv.
    """
    try:
        import tkinter
    except ImportError as exc:
        raise SystemExit(
            "packaging/build.py: tkinter is missing from the build interpreter; "
            f"reinstall Python {BUILD_PYTHON} with its Tcl/Tk libraries"
        ) from exc
    try:
        root = tkinter.Tk()
    except tkinter.TclError as exc:
        raise SystemExit(
            f"packaging/build.py: could not open a Tk root for the preflight: {exc}"
        ) from exc
    try:
        tcl_library = root.tk.eval("info library")
        tk_library = root.tk.eval("set tk_library")
    except tkinter.TclError as exc:
        raise SystemExit(
            f"packaging/build.py: could not read the Tcl/Tk library paths: {exc}"
        ) from exc
    finally:
        root.destroy()
    base = Path(sys.base_prefix).resolve()
    for name, library in (("Tcl", tcl_library), ("Tk", tk_library)):
        resolved = Path(library).resolve()
        if not resolved.is_relative_to(base):
            raise SystemExit(
                f"packaging/build.py: the {name} library {resolved} is outside the "
                f"build interpreter ({base}); the freeze would bundle the host's "
                f"Tcl/Tk instead of Python {BUILD_PYTHON}'s"
            )


def pyinstaller_command(version: str) -> list[str]:
    """Return the PyInstaller argv that freezes the spec into `dist/<version>/`."""
    return [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(DIST_ROOT / version),
        "--workpath",
        str(PYINSTALLER_WORK),
        str(SPEC_PATH),
    ]


def _pyinstaller_error(exc: subprocess.CalledProcessError) -> str:
    """Return the last line the tool printed, never any bundled file's contents."""
    output = exc.stderr or exc.stdout or b""
    text = output.decode("utf-8", "replace") if isinstance(output, bytes) else output
    lines = text.strip().splitlines()
    return lines[-1] if lines else f"exit status {exc.returncode}"


def run_pyinstaller(target: str, version: str) -> Path:
    """Freeze the spec with PyInstaller, and return the directory it wrote.

    The target and version travel in the environment because the spec is
    PyInstaller's own script, not this module's caller.
    """
    environment = os.environ.copy()
    environment[BUILD_TARGET_ENV] = target
    environment[BUILD_VERSION_ENV] = version
    try:
        subprocess.run(
            pyinstaller_command(version),
            cwd=REPO_ROOT,
            env=environment,
            check=True,
            capture_output=True,
        )
    except OSError as exc:
        raise SystemExit(f"packaging/build.py: PyInstaller could not run: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"packaging/build.py: PyInstaller failed: {_pyinstaller_error(exc)}"
        ) from exc
    return DIST_ROOT / version


def main(argv: list[str] | None = None) -> None:
    """Resolve the version, check the interpreter, and freeze `zipseal-gui`.

    The icons are generated before the freeze because the spec bundles the
    window PNG; the Tk preflight then proves the build interpreter's own Tcl/Tk
    can open a window before PyInstaller copies that tree into the bundle.
    """
    parser = argparse.ArgumentParser(
        prog="build.py",
        description="Freeze zipseal-gui for one platform (macOS, Windows, Linux).",
    )
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--skip-sign", action="store_true", help="leave signing to the sign job")
    parser.add_argument("--version", default=read_version())
    args = parser.parse_args(argv)
    if not args.skip_sign:
        raise SystemExit(
            "packaging/build.py: signing is not implemented yet; pass --skip-sign and "
            "let the separate sign job sign the frozen app"
        )
    require_build_python()
    require_host_target(args.target)
    load_icons().generate_icons(args.target)
    tk_preflight()
    dist = run_pyinstaller(args.target, args.version)
    print(f"packaging/build.py: froze {args.target} {args.version} into {dist}")


if __name__ == "__main__":
    main()
