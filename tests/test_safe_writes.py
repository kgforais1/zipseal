"""Failure handling, --force backups and the publication commit point (SPEC.md §6.5)."""

import io
import os
from pathlib import Path

import pytest
from helpers import PASSWORD, archive, args_for, collect_for, extract, leftovers, make_tree

import zipseal.output as output_mod
import zipseal.pipeline as pipeline
from zipseal.errors import VerifyError, WriteError
from zipseal.passwords import Password


@pytest.fixture
def src(tmp_path: Path) -> Path:
    s = tmp_path / "src"
    for i in range(6):
        make_tree(s, {f"f{i}.bin": os.urandom(150_000)})
    (tmp_path / "out").mkdir()
    return s


def test_failure_mid_part_leaves_nothing(
    src: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read error in the fourth file (second part) removes every partial."""
    import zipseal.sources as sources

    real_read = os.read
    calls = {"n": 0}

    def flaky(fd: int, n: int) -> bytes:
        calls["n"] += 1
        if calls["n"] == 12:
            raise OSError(5, "Input/output error")
        return real_read(fd, n)

    monkeypatch.setattr(sources.os, "read", flaky)
    with pytest.raises(WriteError, match=r"f\d\.bin: cannot read: Input/output error"):
        archive([src], tmp_path / "out/b.zip", "--max-size", "400KB")
    monkeypatch.undo()
    assert os.listdir(tmp_path / "out") == []


def test_failure_in_verification_leaves_nothing(
    src: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bad(*a, **kw):  # type: ignore[no-untyped-def]
        raise VerifyError("simulated")

    monkeypatch.setattr(pipeline, "verify_part", bad)
    with pytest.raises(VerifyError):
        archive([src], tmp_path / "out/b.zip", "--max-size", "400KB")
    assert os.listdir(tmp_path / "out") == []


def test_no_verify_still_checks_cap_and_writes(src: Path, tmp_path: Path) -> None:
    results = archive([src], tmp_path / "out/b.zip", "--max-size", "400KB", "--no-verify")
    assert len(results) > 1
    for r in results:
        assert r.path.stat().st_size <= 400_000
        extract(r.path)


def test_force_overwrites_only_own_targets(src: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    (out / "b.zip").write_text("old single")
    (out / "b-part07-of-09.zip").write_text("stale part")
    (out / "unrelated.zip").write_text("leave me")
    args = args_for([src], out / "b.zip", "--force")
    err = io.StringIO()
    with collect_for(args) as c:
        pipeline.write_archive(args, c, lambda _: Password(PASSWORD), err=err)
    assert extract(out / "b.zip")
    assert (out / "b-part07-of-09.zip").read_text() == "stale part"
    assert (out / "unrelated.zip").read_text() == "leave me"
    assert "older part files remain" in err.getvalue()
    assert leftovers(out) == []


def test_force_failure_restores_originals(
    src: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    archive([src], out / "b.zip", "--max-size", "400KB")
    originals = {p.name: p.read_bytes() for p in out.iterdir()}
    assert len(originals) >= 3

    real_link = os.link
    calls = {"n": 0}

    def fail_second(a, b, *rest, **kw):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError(28, "No space left on device")
        return real_link(a, b, *rest, **kw)

    monkeypatch.setattr(output_mod.os, "link", fail_second)
    with pytest.raises(WriteError, match="no archive was written"):
        archive([src], out / "b.zip", "--max-size", "400KB", "--force")
    monkeypatch.undo()
    assert {p.name: p.read_bytes() for p in out.iterdir()} == originals


def test_backup_deletion_failure_after_commit_keeps_outputs(
    src: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    archive([src], out / "b.zip", "--max-size", "400KB")
    old = {p.name: p.read_bytes() for p in out.iterdir()}

    real_unlink = os.unlink
    calls = {"n": 0}

    def fail_second_backup(path, *a, **kw):  # type: ignore[no-untyped-def]
        if "zipseal-backup" in str(path):
            calls["n"] += 1
            if calls["n"] == 2:
                raise PermissionError(13, "Permission denied")
        return real_unlink(path, *a, **kw)

    monkeypatch.setattr(output_mod.os, "unlink", fail_second_backup)
    args = args_for([src], out / "b.zip", "--max-size", "400KB", "--force")
    err = io.StringIO()
    with collect_for(args) as c:
        results = pipeline.write_archive(args, c, lambda _: Password(PASSWORD), err=err)
    monkeypatch.undo()
    assert "could not delete old outputs" in err.getvalue()
    for r in results:
        assert r.path.read_bytes() != old[r.path.name]  # new output kept
        extract(r.path)
    backups = [p for p in out.iterdir() if "zipseal-backup" in p.name]
    assert len(backups) == 1


def test_output_folder_missing(src: Path, tmp_path: Path) -> None:
    with pytest.raises(WriteError, match="output folder does not exist"):
        archive([src], tmp_path / "nope/b.zip")


def test_disk_full_is_a_write_error(
    src: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = os.write

    def full(fd, data):  # type: ignore[no-untyped-def]
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("zipseal.write.os.write", full)
    with pytest.raises(WriteError, match="No space left"):
        archive([src], tmp_path / "out/b.zip")
    monkeypatch.setattr("zipseal.write.os.write", real_write)
    assert os.listdir(tmp_path / "out") == []


def test_part_names_sort_with_many_parts(tmp_path: Path) -> None:
    out = output_mod.Output(tmp_path / "b.zip", force=False)
    for count, first, last in [
        (2, "b-part01-of-02.zip", "b-part02-of-02.zip"),
        (100, "b-part001-of-100.zip", "b-part100-of-100.zip"),
        (1000, "b-part0001-of-1000.zip", "b-part1000-of-1000.zip"),
    ]:
        names = [p.name for p in out.final_names(count)]
        assert names[0] == first and names[-1] == last
        assert names == sorted(names)
