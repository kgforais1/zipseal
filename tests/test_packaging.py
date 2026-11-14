"""Packaging guards, and the helpers a freeze can check without building an app."""

import importlib.util
import platform
import plistlib
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_GLOBS = ["*.dmg", "*.msi", "*.exe", "*.AppImage", "*.tar.gz"]
ARTIFACT_NAMES = [
    "zipseal-gui-0.1.0-macos-arm64.dmg",
    "zipseal-gui-0.1.0-windows-x64.msi",
    "zipseal-gui.exe",
    "installer.AppImage",
    "zipseal-gui-0.1.0-linux-x86_64.tar.gz",
]
OUTPUT_ROOTS = ["dist/", "build/"]
ARTIFACT = "dist/0.1.0/zipseal-gui-0.1.0-macos-arm64.dmg"


def _load_guard():
    path = REPO_ROOT / "hooks" / "scripts" / "check_forbidden_paths.py"
    spec = importlib.util.spec_from_file_location("check_forbidden_paths", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_build():
    path = REPO_ROOT / "packaging" / "build.py"
    spec = importlib.util.spec_from_file_location("packaging_build", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_guard = _load_guard()
read_patterns = _guard.read_patterns
glob_to_regex = _guard.glob_to_regex
main = _guard.main

_build = _load_build()
BUILD_PYTHON = _build.BUILD_PYTHON
collect_data_files = _build.collect_data_files
read_version = _build.read_version
render_info_plist = _build.render_info_plist
version_tuple = _build.version_tuple
render_windows_version_info = _build.render_windows_version_info
require_build_python = _build.require_build_python


def _forbidden_patterns() -> list[str]:
    return read_patterns(REPO_ROOT / ".forbidden-paths")


def _gitignore_lines() -> list[str]:
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
    )


@pytest.mark.parametrize("glob", ARTIFACT_GLOBS)
def test_artifact_globs_are_forbidden(glob: str) -> None:
    patterns = _forbidden_patterns()
    assert glob in patterns


@pytest.mark.parametrize("glob", ARTIFACT_GLOBS)
def test_artifact_globs_are_gitignored(glob: str) -> None:
    assert glob in _gitignore_lines()


@pytest.mark.parametrize("root", OUTPUT_ROOTS)
def test_output_roots_are_forbidden_paths(root: str) -> None:
    patterns = _forbidden_patterns()
    assert root in patterns


@pytest.mark.parametrize("root", OUTPUT_ROOTS)
def test_output_roots_are_gitignored(root: str) -> None:
    lines = _gitignore_lines()
    assert root in lines


@pytest.mark.parametrize(("glob", "name"), list(zip(ARTIFACT_GLOBS, ARTIFACT_NAMES, strict=True)))
def test_artifact_globs_match_release_names(glob: str, name: str) -> None:
    matcher = glob_to_regex(glob)
    assert matcher.match(name)
    assert matcher.match(f"dist/0.1.0/{name}")


def test_tracked_artifact_under_dist_is_rejected(tmp_path: Path, capsys) -> None:
    root = tmp_path / "repo"
    artifact = root / ARTIFACT
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"not a real dmg")
    (root / ".forbidden-paths").write_text(
        (REPO_ROOT / ".forbidden-paths").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _git(root, "init")
    _git(root, "add", ARTIFACT)
    assert main(["--repo-root", str(root)]) == 1
    assert ARTIFACT in capsys.readouterr().err


def test_repo_without_artifacts_passes(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "cli.py").write_text("x = 1\n", encoding="utf-8")
    (root / ".forbidden-paths").write_text(
        (REPO_ROOT / ".forbidden-paths").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _git(root, "init")
    _git(root, "add", "src/cli.py")
    assert main(["--repo-root", str(root)]) == 0


def test_real_tree_is_clean() -> None:
    assert main(["--repo-root", str(REPO_ROOT)]) == 0


def test_read_version_matches_pyproject() -> None:
    expected = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert read_version() == expected["project"]["version"]


def test_version_reaches_every_platform_resource() -> None:
    version = read_version()
    plist = render_info_plist(version)
    assert plist["CFBundleShortVersionString"] == version
    assert plist["CFBundleVersion"] == version
    assert "@VERSION" not in "".join(plist.values())
    resource = render_windows_version_info(version)
    assert f"'{version}'" in resource
    assert version_tuple(version) in resource
    assert "@VERSION" not in resource


def test_linux_desktop_entry_has_required_keys() -> None:
    path = REPO_ROOT / "packaging" / "linux" / "zipseal-gui.desktop"
    fields = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip()
    assert fields["Name"] == "zipseal"
    assert fields["Exec"] == "zipseal-gui"
    assert fields["Icon"] == "zipseal-gui"
    assert fields["Terminal"] == "false"
    assert sorted(token for token in fields["Categories"].split(";") if token) == [
        "Security",
        "Utility",
    ]


def test_apprun_is_tracked_executable() -> None:
    """The index mode is what a checkout restores, not the working-tree bits."""
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-s", "--", "packaging/linux/AppRun"],
        check=True,
        capture_output=True,
        text=True,
    )
    mode, _blob, _stage, path = completed.stdout.split(maxsplit=3)
    assert path.strip() == "packaging/linux/AppRun"
    assert mode == "100755"


def test_macos_entitlements_plist_is_empty() -> None:
    path = REPO_ROOT / "packaging" / "macos" / "entitlements.plist"
    with path.open("rb") as handle:
        assert plistlib.load(handle) == {}


def test_collect_data_files_returns_both_icons() -> None:
    files = collect_data_files()
    assert ("src/zipseal/icon.svg", "zipseal") in files
    assert ("build/icons/icon.png", "zipseal") in files


def test_resolved_data_files_are_absolute_and_the_spec_uses_them() -> None:
    """PyInstaller resolves a relative datas path from `packaging/`, not the repo."""
    root = REPO_ROOT.resolve()
    names: list[str] = []
    for source, destination in _build.resolved_data_files():
        path = Path(source)
        assert path.is_absolute()
        assert path.is_relative_to(root)
        assert not str(path).startswith(str(root / "packaging"))
        assert destination == "zipseal"
        names.append(path.name)
    assert names == ["icon.svg", "icon.png"]
    assert (root / "src" / "zipseal" / "icon.svg").exists()
    spec = (REPO_ROOT / "packaging" / "zipseal-gui.spec").read_text(encoding="utf-8")
    assert "build.resolved_data_files()" in spec


def test_frozen_tree_keeps_both_icons_beside_the_frozen_module(tmp_path: Path, monkeypatch) -> None:
    """A stand-in `sys._MEIPASS` resolves `ICON` and its PNG sibling inside it.

    A frozen module's `__file__` is `_MEIPASS/zipseal/gui.py`, so `gui.ICON` is
    a sibling of that file. The `datas` destinations therefore have to be
    `zipseal`; a `"."` destination would put both files at the bundle root and
    this assertion would fail.
    """
    from zipseal import gui

    meipass = tmp_path / "_MEIPASS"
    for source, destination in collect_data_files():
        # The frozen module is `_MEIPASS/zipseal/gui.py`. A different destination
        # puts the icon somewhere `gui.ICON` does not look.
        assert destination == "zipseal"
        bundled = meipass / destination / Path(source).name
        bundled.parent.mkdir(parents=True, exist_ok=True)
        bundled.write_bytes(b"fixture")
    monkeypatch.setattr(gui, "ICON", (meipass / "zipseal" / "gui.py").with_name("icon.svg"))

    icon = gui.ICON
    png = icon.with_name("icon.png")
    assert icon.is_relative_to(meipass)
    assert png.is_relative_to(meipass)
    assert icon.exists()
    assert png.exists()


class _FakeTkApp:
    def __init__(self, tcl_library: str, tk_library: str) -> None:
        self._libraries = {"info library": tcl_library, "set tk_library": tk_library}

    def eval(self, expression: str) -> str:
        return self._libraries[expression]


class _FakeTkRoot:
    def __init__(self, tcl_library: str, tk_library: str) -> None:
        self.tk = _FakeTkApp(tcl_library, tk_library)
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class _FakeTkinter:
    """Stand in for the `tkinter` module: no window is opened."""

    class TclError(Exception):
        pass

    def __init__(self, tcl_library: str, tk_library: str) -> None:
        self.root = _FakeTkRoot(tcl_library, tk_library)

    def Tk(self) -> _FakeTkRoot:
        return self.root


class _FakeIcons:
    def __init__(self) -> None:
        self.generated: list[str] = []

    def generate_icons(self, target: str) -> None:
        self.generated.append(target)


class _RecordingSubprocess:
    """Stand in for the `subprocess` module: record the command, run nothing.

    `CalledProcessError` has to be this object's attribute. `build.py` catches
    `subprocess.CalledProcessError`, and the tests replace that module.
    """

    CalledProcessError = subprocess.CalledProcessError

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []

    def run(self, command, **kwargs: object) -> None:
        self.calls.append(([str(part) for part in command], dict(kwargs)))


class _StagingSubprocess(_RecordingSubprocess):
    """Record the command and create the staging directory PyInstaller would."""

    def run(self, command, **kwargs: object) -> None:
        super().run(command, **kwargs)
        distpath = Path(command[command.index("--distpath") + 1])
        (distpath / "zipseal-gui").mkdir(parents=True)


def _pin_fake_tkinter(monkeypatch, base_prefix: Path, *, inside: bool) -> _FakeTkinter:
    tcl = base_prefix / "lib" / "tcl9.0"
    tk = base_prefix / "lib" / "tk9.0"
    if not inside:
        tcl = base_prefix.parent / "host" / "lib" / "tcl8.6"
        tk = base_prefix.parent / "host" / "lib" / "tk8.6"
    fake = _FakeTkinter(str(tcl), str(tk))
    monkeypatch.setattr(sys, "base_prefix", str(base_prefix))
    monkeypatch.setitem(sys.modules, "tkinter", fake)
    return fake


def test_tk_preflight_accepts_libraries_inside_the_build_interpreter(
    tmp_path: Path, monkeypatch
) -> None:
    base_prefix = tmp_path / "python"
    fake = _pin_fake_tkinter(monkeypatch, base_prefix, inside=True)
    assert _build.tk_preflight() is None
    assert fake.root.destroyed


def test_tk_preflight_rejects_a_host_tcl_outside_the_build_interpreter(
    tmp_path: Path, monkeypatch
) -> None:
    base_prefix = tmp_path / "python"
    base_prefix.mkdir()
    _pin_fake_tkinter(monkeypatch, base_prefix, inside=False)
    with pytest.raises(SystemExit) as excinfo:
        _build.tk_preflight()
    assert "outside the build interpreter" in str(excinfo.value)


def test_build_refuses_without_skip_sign() -> None:
    with pytest.raises(SystemExit) as excinfo:
        _build.main(["--target", "linux"])
    assert "--skip-sign" in str(excinfo.value)


def _ready_to_freeze(monkeypatch, tmp_path: Path, recorder: _RecordingSubprocess) -> _FakeIcons:
    """Stub the checks around PyInstaller and point its output at `tmp_path`."""
    base_prefix = tmp_path / "python"
    _pin_fake_tkinter(monkeypatch, base_prefix, inside=True)
    monkeypatch.setattr(_build, "require_build_python", lambda: None)
    monkeypatch.setattr(_build, "host_target", lambda: "macos")
    monkeypatch.setattr(_build, "DIST_ROOT", tmp_path / "dist")
    icons = _FakeIcons()
    monkeypatch.setattr(_build, "load_icons", lambda: icons)
    monkeypatch.setattr(_build, "subprocess", recorder)
    return icons


def test_build_runs_pyinstaller_on_the_spec_into_the_versioned_dist(
    tmp_path: Path, monkeypatch
) -> None:
    version = read_version()
    recorder = _StagingSubprocess()
    icons = _ready_to_freeze(monkeypatch, tmp_path, recorder)
    previous = tmp_path / "dist" / version / "kept"
    previous.parent.mkdir(parents=True)
    previous.write_text("complete", encoding="utf-8")

    _build.main(["--target", "macos", "--skip-sign", "--version", version])

    assert icons.generated == ["macos"]
    assert len(recorder.calls) == 1
    command, kwargs = recorder.calls[0]
    assert command[:3] == [sys.executable, "-m", "PyInstaller"]
    assert command[-1] == str(REPO_ROOT / "packaging" / "zipseal-gui.spec")
    staging = tmp_path / "dist" / f"{version}.partial"
    published = tmp_path / "dist" / version
    assert command[command.index("--distpath") + 1] == str(staging)
    assert str(REPO_ROOT / "build" / "pyinstaller") in command
    assert not staging.exists()
    assert (published / "zipseal-gui").is_dir()
    assert not previous.exists()
    environment = kwargs["env"]
    assert isinstance(environment, dict)
    assert environment[_build.BUILD_TARGET_ENV] == "macos"
    assert environment[_build.BUILD_VERSION_ENV] == version


def test_host_target_maps_darwin_through_icons_host_key(monkeypatch) -> None:
    """The resvg host key says darwin; the build target for that machine is macos."""

    class _Icons:
        def host_key(self) -> tuple[str, str]:
            return ("darwin", "arm64")

    monkeypatch.setattr(_build, "load_icons", lambda: _Icons())
    assert _build.host_target() == "macos"


def test_build_rejects_a_target_for_another_platform(monkeypatch) -> None:
    """A mismatched target stops before icons or PyInstaller."""
    monkeypatch.setattr(_build, "require_build_python", lambda: None)
    monkeypatch.setattr(_build, "host_target", lambda: "linux")
    icons = _FakeIcons()
    monkeypatch.setattr(_build, "load_icons", lambda: icons)
    recorder = _RecordingSubprocess()
    monkeypatch.setattr(_build, "subprocess", recorder)

    with pytest.raises(SystemExit) as excinfo:
        _build.main(["--target", "macos", "--skip-sign"])

    assert "does not match" in str(excinfo.value)
    assert "linux" in str(excinfo.value)
    assert icons.generated == []
    assert recorder.calls == []


def test_build_rejects_a_version_before_icons_or_pyinstaller(monkeypatch, tmp_path: Path) -> None:
    """A version that is not one to four numbers never starts the icon build."""
    recorder = _RecordingSubprocess()
    icons = _ready_to_freeze(monkeypatch, tmp_path, recorder)

    with pytest.raises(SystemExit) as excinfo:
        _build.main(["--target", "macos", "--skip-sign", "--version", "0.2.0rc1"])

    assert "not one to four numbers" in str(excinfo.value)
    assert icons.generated == []
    assert recorder.calls == []


def test_build_rejects_a_non_ascii_version(monkeypatch, tmp_path: Path) -> None:
    """A Unicode digit is not a version: `int` would raise or accept the wrong number."""
    recorder = _RecordingSubprocess()
    icons = _ready_to_freeze(monkeypatch, tmp_path, recorder)

    with pytest.raises(SystemExit, match="not one to four numbers"):
        _build.main(["--target", "macos", "--skip-sign", "--version", "1\u00b2"])

    with pytest.raises(SystemExit, match="not one to four numbers"):
        version_tuple("\u0661")
    assert icons.generated == []
    assert recorder.calls == []


def test_remove_tree_refuses_a_path_outside_dist(tmp_path: Path, monkeypatch) -> None:
    """`..` and a symlink out of `dist/` are not deleted."""
    root = tmp_path / "dist"
    root.mkdir()
    monkeypatch.setattr(_build, "DIST_ROOT", root)
    outside = tmp_path / "escape"
    outside.mkdir()
    (outside / "kept").write_text("stay", encoding="utf-8")
    link = root / "linked"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(SystemExit, match="refusing to touch"):
        _build._remove_tree(root / ".." / "escape")
    with pytest.raises(SystemExit, match="refusing to touch"):
        _build._remove_tree(link)

    assert (outside / "kept").read_text(encoding="utf-8") == "stay"


def test_publish_restores_the_previous_tree_when_the_new_one_cannot_move(
    tmp_path: Path, monkeypatch
) -> None:
    """A failed rename of the new tree puts the previous app back and drops the partial."""
    root = tmp_path / "dist"
    root.mkdir()
    monkeypatch.setattr(_build, "DIST_ROOT", root)
    published = root / "0.1.0"
    published.mkdir()
    (published / "kept").write_text("complete", encoding="utf-8")
    staging = root / "0.1.0.partial"
    staging.mkdir()
    (staging / "new").write_text("partial", encoding="utf-8")
    real_rename = Path.rename

    def fail_staging_move(self: Path, target: Path) -> Path:
        if self == staging:
            raise OSError("device busy")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_staging_move)

    with pytest.raises(SystemExit, match="could not publish"):
        _build._publish_dist(staging, published)

    assert (published / "kept").read_text(encoding="utf-8") == "complete"
    assert not staging.exists()
    assert not (root / "0.1.0.previous").exists()


def test_build_rejects_a_version_that_escapes_dist(monkeypatch, tmp_path: Path) -> None:
    """`..` or a slash would make `--distpath` point outside `dist/`."""
    recorder = _RecordingSubprocess()
    icons = _ready_to_freeze(monkeypatch, tmp_path, recorder)

    with pytest.raises(SystemExit) as excinfo:
        _build.main(["--target", "macos", "--skip-sign", "--version", "../outside"])

    assert "single path component" in str(excinfo.value)
    assert icons.generated == []
    assert recorder.calls == []
    assert not (tmp_path / "outside").exists()


def test_a_failed_freeze_keeps_the_published_tree(monkeypatch, tmp_path: Path) -> None:
    """PyInstaller failing deletes its partial tree and leaves the last good app."""
    version = read_version()

    class _Failing(_RecordingSubprocess):
        def run(self, command, **kwargs: object) -> None:
            super().run(command, **kwargs)
            distpath = Path(command[command.index("--distpath") + 1])
            distpath.mkdir(parents=True)
            (distpath / "incomplete").write_text("partial", encoding="utf-8")
            raise subprocess.CalledProcessError(1, command, stderr=b"analysis failed\n")

    recorder = _Failing()
    _ready_to_freeze(monkeypatch, tmp_path, recorder)
    published = tmp_path / "dist" / version
    published.mkdir(parents=True)
    (published / "kept").write_text("complete", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        _build.main(["--target", "macos", "--skip-sign", "--version", version])

    assert "analysis failed" in str(excinfo.value)
    assert (published / "kept").read_text(encoding="utf-8") == "complete"
    assert not (tmp_path / "dist" / f"{version}.partial").exists()


def test_tk_preflight_names_xvfb_when_there_is_no_display(monkeypatch, tmp_path: Path) -> None:
    """A headless TclError is a missing display, not a broken Tcl/Tk install."""

    class _Headless(_FakeTkinter):
        def Tk(self) -> _FakeTkRoot:
            raise self.TclError("no display name and no $DISPLAY environment variable")

    base_prefix = tmp_path / "python"
    monkeypatch.setattr(sys, "base_prefix", str(base_prefix))
    monkeypatch.setitem(sys.modules, "tkinter", _Headless("unused", "unused"))

    with pytest.raises(SystemExit) as excinfo:
        _build.tk_preflight()

    assert "xvfb-run" in str(excinfo.value)


def test_require_build_python_accepts_the_pinned_interpreter(monkeypatch) -> None:
    monkeypatch.setattr(platform, "python_version", lambda: BUILD_PYTHON)
    assert require_build_python() is None


def test_require_build_python_rejects_any_other_interpreter(monkeypatch) -> None:
    monkeypatch.setattr(platform, "python_version", lambda: "3.12.0")
    with pytest.raises(SystemExit) as excinfo:
        require_build_python()
    assert BUILD_PYTHON in str(excinfo.value)
