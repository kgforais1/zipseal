"""The double-clickable launcher and the icon helper behave as specified."""

import platform
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LAUNCHER = REPO / "zipseal-gui.command"
SET_ICON = REPO / "scripts" / "set-icon.sh"
TIMEOUT = 30
# The launcher needs only these external tools; xattr exists on macOS only.
TOOLS = ("dirname", "basename", "xattr")


def _expected_argv(clone: Path) -> list[str]:
    return ["run", "--managed-python", "--project", str(clone), "zipseal-gui"]


def _tool_path(folder: Path) -> str:
    """A PATH holding links to the launcher's tools and no real uv."""
    folder.mkdir(parents=True, exist_ok=True)
    for tool in TOOLS:
        found = shutil.which(tool)
        if found:
            (folder / tool).symlink_to(found)
    return str(folder)


def _stub_uv(folder: Path, out: Path) -> None:
    """Write a fake uv that records its arguments, one per line."""
    folder.mkdir(parents=True, exist_ok=True)
    stub = folder / "uv"
    stub.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > '{out}'\n")
    stub.chmod(0o755)


def _copy_launcher(folder: Path) -> Path:
    """Copy the launcher alone, so tests never touch the real file's icon."""
    folder.mkdir(parents=True, exist_ok=True)
    copy = folder / LAUNCHER.name
    shutil.copy2(LAUNCHER, copy)
    return copy


def _run(launcher: Path, *, path: str, home: Path, cwd: Path, stdin: bytes | None = None):
    return subprocess.run(
        [str(launcher)],
        env={"PATH": path, "HOME": str(home)},
        cwd=cwd,
        input=stdin,
        stdin=subprocess.DEVNULL if stdin is None else None,
        capture_output=True,
        timeout=TIMEOUT,
        check=False,
    )


def test_launcher_is_tracked_as_executable_shell_script() -> None:
    staged = subprocess.run(
        ["git", "ls-files", "-s", LAUNCHER.name],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        check=True,
    ).stdout
    assert staged.startswith("100755 ")
    assert LAUNCHER.stat().st_mode & 0o111, "working-tree copy lost its exec bit"
    assert LAUNCHER.read_text().startswith("#!/bin/sh\n")


@pytest.mark.parametrize("script", [LAUNCHER, SET_ICON])
def test_scripts_parse(script: Path) -> None:
    subprocess.run(["sh", "-n", str(script)], timeout=TIMEOUT, check=True)


def test_launcher_runs_uv_from_path(tmp_path: Path) -> None:
    out = tmp_path / "args"
    _stub_uv(tmp_path / "bin", out)
    launcher = _copy_launcher(tmp_path / "clone")
    tools = _tool_path(tmp_path / "tools")
    result = _run(launcher, path=f"{tmp_path / 'bin'}:{tools}", home=tmp_path, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert out.read_text().splitlines() == _expected_argv(launcher.parent)


def test_launcher_finds_uv_outside_path(tmp_path: Path) -> None:
    home = tmp_path / "home"
    out = tmp_path / "args"
    _stub_uv(home / ".local" / "bin", out)
    launcher = _copy_launcher(tmp_path / "clone")
    result = _run(launcher, path=_tool_path(tmp_path / "tools"), home=home, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert out.read_text().splitlines() == _expected_argv(launcher.parent)


def test_launcher_handles_spaced_clone_and_foreign_cwd(tmp_path: Path) -> None:
    out = tmp_path / "args"
    _stub_uv(tmp_path / "bin", out)
    launcher = _copy_launcher(tmp_path / "my clone" / "zip seal")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    tools = _tool_path(tmp_path / "tools")
    result = _run(launcher, path=f"{tmp_path / 'bin'}:{tools}", home=tmp_path, cwd=elsewhere)
    assert result.returncode == 0, result.stderr
    assert out.read_text().splitlines() == _expected_argv(launcher.parent)


@pytest.mark.skipif(
    any(Path(d, "uv").exists() for d in ("/opt/homebrew/bin", "/usr/local/bin")),
    reason="uv in a fixed fallback folder cannot be hidden from the launcher",
)
@pytest.mark.parametrize("stdin", [b"\n", b""], ids=["return", "eof"])
def test_launcher_without_uv_explains_and_exits(tmp_path: Path, stdin: bytes) -> None:
    home = tmp_path / "home"
    home.mkdir()
    launcher = _copy_launcher(tmp_path / "clone")
    tools = _tool_path(tmp_path / "tools")
    result = _run(launcher, path=tools, home=home, cwd=tmp_path, stdin=stdin)
    assert result.returncode == 1
    assert b"https://docs.astral.sh/uv/" in result.stderr


def _session_can_set_icons(probe: Path) -> bool:
    """Ask AppKit directly, without the helper, whether icons can be set here."""
    probe.write_text("probe\n")
    script = (
        'ObjC.import("AppKit");'
        "var image = $.NSWorkspace.sharedWorkspace.iconForFile('/bin/sh');"
        f"$.NSWorkspace.sharedWorkspace.setIconForFileOptions(image, {str(probe)!r}, 0)"
    )
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", script],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        check=False,
    )
    return result.stdout.strip() == "true"


def test_set_icon_keeps_file_bytes(tmp_path: Path) -> None:
    target = tmp_path / "launcher copy.command"
    target.write_text("#!/bin/sh\n")
    result = subprocess.run(
        [str(SET_ICON), str(target)], capture_output=True, timeout=TIMEOUT, check=False
    )
    assert result.returncode == 0
    assert result.stderr == b""
    assert target.read_text() == "#!/bin/sh\n"


@pytest.mark.skipif(platform.system() != "Darwin", reason="Finder icons are macOS only")
def test_set_icon_sets_finder_icon(tmp_path: Path) -> None:
    if not _session_can_set_icons(tmp_path / "probe"):
        pytest.skip("AppKit cannot set icons in this session (headless runner?)")
    target = tmp_path / "launcher copy.command"
    target.write_text("#!/bin/sh\n")
    subprocess.run([str(SET_ICON), str(target)], timeout=TIMEOUT, check=True)
    subprocess.run(
        ["xattr", "-p", "com.apple.ResourceFork", str(target)],
        capture_output=True,
        timeout=TIMEOUT,
        check=True,
    )
