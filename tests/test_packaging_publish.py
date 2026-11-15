"""Publish-backup order. `build.py` is loaded by path so `packaging` is not imported.

`packaging` must not be on pytest's pythonpath: it would shadow the PyPI
`packaging` distribution.
"""

import importlib.util
import os
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


def test_a_missing_older_backup_is_not_reused(tmp_path: Path, monkeypatch) -> None:
    """The next aside name sits above a leftover `.previous-2`."""
    root = tmp_path / "dist"
    root.mkdir()
    monkeypatch.setattr(_build, "DIST_ROOT", root)
    (root / "0.1.0.previous-2").mkdir()
    assert _build._aside_path(root / "0.1.0").name == "0.1.0.previous-3"


def test_recovery_restores_the_newer_backup_when_a_higher_suffix_is_older(
    tmp_path: Path, monkeypatch
) -> None:
    """Publication time wins: a newer `.previous` beats an older `.previous-2`."""
    root = tmp_path / "dist"
    root.mkdir()
    monkeypatch.setattr(_build, "DIST_ROOT", root)
    older = root / "0.1.0.previous-2"
    newer = root / "0.1.0.previous"
    for path, text, when in ((older, "old", 1_000), (newer, "new", 2_000)):
        path.mkdir()
        (path / "kept").write_text(text, encoding="utf-8")
        os.utime(path, (when, when))

    _build._recover_published(root / "0.1.0")

    assert (root / "0.1.0" / "kept").read_text(encoding="utf-8") == "new"
    assert not newer.exists()
    assert (older / "kept").read_text(encoding="utf-8") == "old"


def _dist(tmp_path: Path, monkeypatch) -> Path:
    """Point publish at a fresh `dist/` and return it."""
    root = tmp_path / "dist"
    root.mkdir()
    monkeypatch.setattr(_build, "DIST_ROOT", root)
    return root


def test_publish_stamps_the_backup_it_just_set_aside(tmp_path: Path, monkeypatch) -> None:
    """The aside mtime is newer than a leftover, even when the tree itself is old."""
    root = _dist(tmp_path, monkeypatch)
    older = root / "0.1.0.previous"
    older.mkdir()
    os.utime(older, (1_000, 1_000))
    published = root / "0.1.0"
    published.mkdir()
    (published / "kept").write_text("current", encoding="utf-8")
    os.utime(published, (1_000, 1_000))
    staging = root / "0.1.0.partial"
    staging.mkdir()
    (staging / "app").write_text("fresh", encoding="utf-8")
    seen: dict[str, int] = {}
    real_remove = _build._remove_tree

    def record(path: Path) -> None:
        if path.name == "0.1.0.previous-2":
            seen["mtime"] = path.lstat().st_mtime_ns
        real_remove(path)

    monkeypatch.setattr(_build, "_remove_tree", record)
    _build._publish_dist(staging, published)
    assert seen["mtime"] > older.lstat().st_mtime_ns
    assert (published / "app").read_text(encoding="utf-8") == "fresh"
    assert not (root / "0.1.0.previous-2").exists()


def test_a_failed_stamp_puts_the_current_app_back(tmp_path: Path, monkeypatch) -> None:
    """A stamp error restores the app and leaves no `.previous` behind."""
    root = _dist(tmp_path, monkeypatch)
    published = root / "0.1.0"
    published.mkdir()
    (published / "kept").write_text("complete", encoding="utf-8")
    staging = root / "0.1.0.partial"
    staging.mkdir()

    def deny_utime(*_args: object, **_kwargs: object) -> None:
        raise OSError(13, "not permitted")

    monkeypatch.setattr(_build.os, "utime", deny_utime)
    with pytest.raises(SystemExit, match="could not move the previous freeze aside"):
        _build._publish_dist(staging, published)
    assert (published / "kept").read_text(encoding="utf-8") == "complete"
    assert not (root / "0.1.0.previous").exists()


def test_a_failed_stamp_names_the_backup_it_cannot_restore(tmp_path: Path, monkeypatch) -> None:
    """When the stamp fails and the tree cannot move back, the error names it."""
    root = _dist(tmp_path, monkeypatch)
    published = root / "0.1.0"
    published.mkdir()
    (published / "kept").write_text("complete", encoding="utf-8")
    staging = root / "0.1.0.partial"
    staging.mkdir()
    real_rename = Path.rename

    def rename(self: Path, target: Path) -> Path:
        if self.name == "0.1.0.previous" and target == published:
            raise OSError(16, "device busy")
        return real_rename(self, target)

    def deny_utime(*_args: object, **_kwargs: object) -> None:
        raise OSError(13, "not permitted")

    monkeypatch.setattr(Path, "rename", rename)
    monkeypatch.setattr(_build.os, "utime", deny_utime)
    with pytest.raises(SystemExit, match="still at 0.1.0.previous"):
        _build._publish_dist(staging, published)
    assert (root / "0.1.0.previous" / "kept").read_text(encoding="utf-8") == "complete"
    assert not published.exists()
