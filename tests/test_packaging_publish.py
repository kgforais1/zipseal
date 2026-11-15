"""Publish-backup order. `build.py` is loaded by path so `packaging` is not imported.

`packaging` must not be on pytest's pythonpath: it would shadow the PyPI
`packaging` distribution.
"""

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_build():
    """Load `packaging/build.py` by path, as `test_packaging.py` does."""
    path = REPO_ROOT / "packaging" / "build.py"
    spec = importlib.util.spec_from_file_location("packaging_build_publish", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_build = _load_build()


class _FakeIcons:
    """Stand in for the icons module: record the target, generate nothing."""

    def __init__(self) -> None:
        self.generated: list[str] = []

    def generate_icons(self, target: str) -> None:
        self.generated.append(target)


class _FreezeSubprocess:
    """Stand in for the `subprocess` module: record the command, run nothing.

    `CalledProcessError` has to be this object's attribute. `build.py` catches
    `subprocess.CalledProcessError`, and the tests replace that module.
    """

    CalledProcessError = subprocess.CalledProcessError

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []

    def run(self, command, **kwargs: object) -> None:
        argv = [str(part) for part in command]
        self.calls.append((argv, dict(kwargs)))
        if argv and argv[0].endswith("hdiutil"):
            Path(argv[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(argv[-1]).write_bytes(b"dmg")
            return
        distpath = Path(command[command.index("--distpath") + 1])
        (distpath / "zipseal-gui").mkdir(parents=True)
        (distpath / "zipseal-gui.app" / "Contents").mkdir(parents=True)


def _ready_main(monkeypatch, tmp_path: Path, runner: _FreezeSubprocess) -> _FakeIcons:
    """Stub the checks around the freeze and point its `dist/` at `tmp_path`."""
    monkeypatch.setattr(_build, "require_build_python", lambda: None)
    monkeypatch.setattr(_build, "host_target", lambda: "macos")
    monkeypatch.setattr(_build, "DIST_ROOT", tmp_path / "dist")
    monkeypatch.setattr(_build, "tk_preflight", lambda: None)
    icons = _FakeIcons()
    monkeypatch.setattr(_build, "load_icons", lambda: icons)
    monkeypatch.setattr(_build, "subprocess", runner)
    return icons


def test_a_missing_older_backup_is_not_reused(tmp_path: Path, monkeypatch) -> None:
    """The next aside name sits above a leftover `.previous-2`."""
    root = tmp_path / "dist"
    root.mkdir()
    monkeypatch.setattr(_build, "DIST_ROOT", root)
    (root / "0.1.0.previous-2").mkdir()
    assert _build._aside_path(root / "0.1.0").name == "0.1.0.previous-3"


def test_recovery_restores_the_highest_suffix_even_when_its_mtime_is_older(
    tmp_path: Path, monkeypatch
) -> None:
    """A touched `.previous` does not beat the later `.previous-2`."""
    root = tmp_path / "dist"
    root.mkdir()
    monkeypatch.setattr(_build, "DIST_ROOT", root)
    leftover = root / "0.1.0.previous"
    latest = root / "0.1.0.previous-2"
    leftover.mkdir()
    (leftover / "kept").write_text("old", encoding="utf-8")
    latest.mkdir()
    (latest / "kept").write_text("new", encoding="utf-8")
    os.utime(leftover, (2_000, 2_000))
    os.utime(latest, (1_000, 1_000))

    _build._recover_published(root / "0.1.0")

    assert (root / "0.1.0" / "kept").read_text(encoding="utf-8") == "new"
    assert not latest.exists()
    assert (leftover / "kept").read_text(encoding="utf-8") == "old"


def test_a_failed_aside_rename_keeps_the_app_in_place(tmp_path: Path, monkeypatch) -> None:
    """A busy rename leaves the current app where it is and creates no backup."""
    root = tmp_path / "dist"
    root.mkdir()
    monkeypatch.setattr(_build, "DIST_ROOT", root)
    published = root / "0.1.0"
    published.mkdir()
    (published / "kept").write_text("complete", encoding="utf-8")
    staging = root / "0.1.0.partial"
    staging.mkdir()
    real_rename = Path.rename

    def fail_aside(self: Path, target: Path) -> Path:
        if self == published:
            raise OSError(16, "device busy")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_aside)
    with pytest.raises(SystemExit, match="could not move the previous freeze aside"):
        _build._publish_dist(staging, published)
    assert (published / "kept").read_text(encoding="utf-8") == "complete"
    assert not (root / "0.1.0.previous").exists()


def test_macos_dmg_packs_the_app_and_an_applications_link(tmp_path: Path, monkeypatch) -> None:
    """The disk image command is arm64-only and wraps the app plus /Applications."""
    root = tmp_path / "dist"
    root.mkdir()
    monkeypatch.setattr(_build, "DIST_ROOT", root)
    monkeypatch.setattr(_build.platform, "machine", lambda: "arm64")
    published = root / "0.1.0"
    app = published / "zipseal-gui.app"
    (app / "Contents").mkdir(parents=True)
    recorded: dict[str, object] = {}

    def run(command, **kwargs: object) -> None:
        source = Path(command[command.index("-srcfolder") + 1])
        recorded["command"] = [str(part) for part in command]
        recorded["source"] = source
        assert (source / "zipseal-gui.app" / "Contents").is_dir()
        assert (source / "Applications").readlink() == Path("/Applications")
        Path(command[-1]).write_bytes(b"dmg")

    monkeypatch.setattr(_build.subprocess, "run", run)
    image = _build.make_macos_dmg(published, "0.1.0")
    source = published / ".dmg-staging"
    command = recorded["command"]
    assert command == [
        "/usr/bin/hdiutil",
        "create",
        "-volname",
        "zipseal-gui",
        "-srcfolder",
        str(source),
        "-ov",
        "-format",
        "UDZO",
        str(image),
    ]
    assert image.name == "zipseal-gui-0.1.0-macos-arm64.dmg"
    assert image.read_bytes() == b"dmg"
    recorded_source = recorded["source"]
    assert recorded_source == source
    assert not source.exists()


def test_macos_dmg_refuses_a_non_arm64_machine(tmp_path: Path, monkeypatch) -> None:
    """An Intel Mac does not get an image named as if it were arm64."""
    root = tmp_path / "dist"
    root.mkdir()
    monkeypatch.setattr(_build, "DIST_ROOT", root)
    monkeypatch.setattr(_build.platform, "machine", lambda: "x86_64")
    published = root / "0.1.0"
    (published / "zipseal-gui.app").mkdir(parents=True)
    with pytest.raises(SystemExit, match="arm64"):
        _build.make_macos_dmg(published, "0.1.0")


def test_macos_dmg_refuses_a_directory_named_for_another_version(
    tmp_path: Path, monkeypatch
) -> None:
    """The image name and the directory it is written into name the same version."""
    root = tmp_path / "dist"
    root.mkdir()
    monkeypatch.setattr(_build, "DIST_ROOT", root)
    monkeypatch.setattr(_build.platform, "machine", lambda: "arm64")
    published = root / "0.1.0"
    (published / "zipseal-gui.app").mkdir(parents=True)
    with pytest.raises(SystemExit, match="does not match"):
        _build.make_macos_dmg(published, "0.2.0")
    assert not list(published.glob("*.dmg"))


def test_macos_dmg_replaces_a_staging_symlink_without_following_it(
    tmp_path: Path, monkeypatch
) -> None:
    """A leftover `.dmg-staging` link is removed; the directory it names stays."""
    root = tmp_path / "dist"
    root.mkdir()
    monkeypatch.setattr(_build, "DIST_ROOT", root)
    monkeypatch.setattr(_build.platform, "machine", lambda: "arm64")
    published = root / "0.1.0"
    (published / "zipseal-gui.app" / "Contents").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "kept").write_text("stay", encoding="utf-8")
    try:
        (published / ".dmg-staging").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("this host cannot create a directory symlink")

    def run(command, **kwargs: object) -> None:
        Path(command[-1]).write_bytes(b"dmg")

    monkeypatch.setattr(_build.subprocess, "run", run)
    _build.make_macos_dmg(published, "0.1.0")
    assert (outside / "kept").read_text(encoding="utf-8") == "stay"
    assert not (published / ".dmg-staging").exists()


def test_macos_dmg_removes_a_directory_left_where_the_image_should_be(
    tmp_path: Path, monkeypatch
) -> None:
    """A failed hdiutil that left a directory does not hide the hdiutil error."""
    root = tmp_path / "dist"
    root.mkdir()
    monkeypatch.setattr(_build, "DIST_ROOT", root)
    monkeypatch.setattr(_build.platform, "machine", lambda: "arm64")
    published = root / "0.1.0"
    (published / "zipseal-gui.app" / "Contents").mkdir(parents=True)

    def run(command, **kwargs: object) -> None:
        Path(command[-1]).mkdir()
        raise subprocess.CalledProcessError(1, command, stderr=b"hdiutil exploded\n")

    monkeypatch.setattr(_build.subprocess, "run", run)
    destination = published / "zipseal-gui-0.1.0-macos-arm64.dmg"
    with pytest.raises(SystemExit, match="hdiutil exploded"):
        _build.make_macos_dmg(published, "0.1.0")
    assert not destination.exists()
    assert (published / "zipseal-gui.app").is_dir()


def test_macos_dmg_unlinks_a_symlink_at_the_image_path(tmp_path: Path, monkeypatch) -> None:
    """A planted link must not let `hdiutil -ov` write through to its target."""
    root = tmp_path / "dist"
    root.mkdir()
    monkeypatch.setattr(_build, "DIST_ROOT", root)
    monkeypatch.setattr(_build.platform, "machine", lambda: "arm64")
    published = root / "0.1.0"
    (published / "zipseal-gui.app" / "Contents").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "secret"
    target.write_bytes(b"untouched")
    destination = published / "zipseal-gui-0.1.0-macos-arm64.dmg"
    try:
        destination.symlink_to(target)
    except OSError:
        pytest.skip("this host cannot create a symlink")

    def run(command, **kwargs: object) -> None:
        Path(command[-1]).write_bytes(b"dmg")

    monkeypatch.setattr(_build.subprocess, "run", run)
    image = _build.make_macos_dmg(published, "0.1.0")
    assert image == destination
    assert not destination.is_symlink()
    assert destination.is_file()
    assert destination.read_bytes() == b"dmg"
    assert target.read_bytes() == b"untouched"


def test_a_staging_copy_failure_keeps_the_published_tree(tmp_path: Path, monkeypatch) -> None:
    """A failed copy is a `SystemExit`: the partial tree goes, the app stays."""
    version = _build.read_version()
    runner = _FreezeSubprocess()
    _ready_main(monkeypatch, tmp_path, runner)
    monkeypatch.setattr(_build.platform, "machine", lambda: "arm64")

    def fail_copy(*args: object, **kwargs: object) -> object:
        raise OSError("no space left on device")

    monkeypatch.setattr(shutil, "copytree", fail_copy)
    published = tmp_path / "dist" / version
    published.mkdir(parents=True)
    (published / "kept").write_text("complete", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        _build.main(["--target", "macos", "--skip-sign", "--version", version])

    assert str(excinfo.value).startswith("packaging/build.py: could not stage")
    assert (published / "kept").read_text(encoding="utf-8") == "complete"
    assert not (tmp_path / "dist" / f"{version}.partial").exists()


def test_a_staging_cleanup_failure_after_a_good_image_does_not_publish(
    tmp_path: Path, monkeypatch
) -> None:
    """A `.dmg-staging` that cannot be removed after `hdiutil` fails the build."""
    version = _build.read_version()
    runner = _FreezeSubprocess()
    _ready_main(monkeypatch, tmp_path, runner)
    monkeypatch.setattr(_build.platform, "machine", lambda: "arm64")
    image_name = f"zipseal-gui-{version}-macos-arm64.dmg"
    real_clear = _build._clear_entry

    def fail_final_cleanup(directory: Path, name: str) -> None:
        if name == ".dmg-staging" and (directory / image_name).exists():
            raise OSError("device busy")
        real_clear(directory, name)

    monkeypatch.setattr(_build, "_clear_entry", fail_final_cleanup)
    published = tmp_path / "dist" / version
    published.mkdir(parents=True)
    (published / "kept").write_text("complete", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        _build.main(["--target", "macos", "--skip-sign", "--version", version])

    assert "could not be removed" in str(excinfo.value)
    assert (published / "kept").read_text(encoding="utf-8") == "complete"
    assert not (published / image_name).exists()
    assert not (tmp_path / "dist" / f"{version}.partial").exists()


def test_build_refuses_a_non_arm64_mac_before_icons_or_pyinstaller(
    tmp_path: Path, monkeypatch
) -> None:
    """An Intel Mac stops with the arm64 message before anything is generated."""
    version = _build.read_version()
    runner = _FreezeSubprocess()
    icons = _ready_main(monkeypatch, tmp_path, runner)
    monkeypatch.setattr(_build.platform, "machine", lambda: "x86_64")

    with pytest.raises(SystemExit) as excinfo:
        _build.main(["--target", "macos", "--skip-sign", "--version", version])

    assert "arm64" in str(excinfo.value)
    assert "x86_64" in str(excinfo.value)
    assert icons.generated == []
    assert runner.calls == []
