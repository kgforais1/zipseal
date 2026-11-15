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
