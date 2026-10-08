"""--hide-names nesting (SPEC.md §6.7) and --manifest (§4, §6.8)."""

import os
import zipfile
from pathlib import Path

import pytest
from helpers import PASSWORD, archive, extract, leftovers, make_tree
from stream_unzip import stream_unzip

from zipseal import plan
from zipseal.errors import InputError, VerifyError
from zipseal.passwords import Password
from zipseal.verify import verify_part


def inner_files(part: Path) -> dict[str, bytes]:
    outer = extract(part)
    assert list(outer) == ["payload.zip"]
    files = {}
    for name, _, chunks in stream_unzip([outer["payload.zip"]]):
        files[name.decode()] = b"".join(chunks)
    return files


@pytest.fixture
def src(tmp_path: Path) -> Path:
    s = tmp_path / "src"
    make_tree(s, {"secret-name.txt": "hidden", "empty/": "", "sub/x.bin": os.urandom(5000)})
    (tmp_path / "out").mkdir()
    return s


def test_names_hidden_and_round_trip(src: Path, tmp_path: Path) -> None:
    [r] = archive([src], tmp_path / "out/b.zip", "--hide-names")
    raw = r.path.read_bytes()
    assert b"secret-name" not in raw
    with zipfile.ZipFile(r.path) as zf:
        [info] = zf.infolist()
    assert info.filename == "payload.zip"
    assert info.date_time == (1980, 1, 1, 0, 0, 0)
    files = inner_files(r.path)
    assert files["src/secret-name.txt"] == b"hidden"
    assert files["src/sub/x.bin"] == (src / "sub/x.bin").read_bytes()
    assert files["src/empty/"] == b""


def test_parts_under_cap_with_incompressible_data(tmp_path: Path) -> None:
    src = tmp_path / "src"
    for i in range(12):
        make_tree(src, {f"f{i:02d}.bin": os.urandom(180_000)})
    (tmp_path / "out").mkdir()
    cap = 1_000_000
    results = archive([src], tmp_path / "out/b.zip", "--hide-names", "--max-size", str(cap))
    assert len(results) > 1
    seen: dict[str, bytes] = {}
    for r in results:
        assert r.path.stat().st_size <= cap
        seen.update(inner_files(r.path))
    assert len(seen) == 12


@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_cap_at_the_admission_threshold(tmp_path: Path, delta: int) -> None:
    """One incompressible file; caps one byte either side of its exact need."""
    src = tmp_path / "src"
    make_tree(src, {"f.bin": os.urandom(300_000)})
    (tmp_path / "out").mkdir()
    entry_cost = plan.cost(
        _entry(src / "f.bin", "src/f.bin"), index=0, offset=0, central_so_far=0, encrypted=False
    )
    inner = entry_cost.local + entry_cost.central + plan.END_RECORDS
    need = plan.deflate_bound(inner) + plan.outer_fixed(False)
    cap = need + delta
    if delta < 0:
        with pytest.raises(InputError, match="cannot fit"):
            archive([src], tmp_path / "out/b.zip", "--hide-names", "--max-size", str(cap))
        return
    [r] = archive([src], tmp_path / "out/b.zip", "--hide-names", "--max-size", str(cap))
    assert r.path.stat().st_size <= cap


def _entry(path: Path, arcname: str):  # type: ignore[no-untyped-def]
    from datetime import datetime

    from zipseal.collect import FileEntry

    return FileEntry(0, (), arcname, path.stat().st_size, datetime(2026, 1, 1), 0o644, False, ())


def test_empty_inner_zip(tmp_path: Path) -> None:
    (tmp_path / "src/a/b").mkdir(parents=True)
    (tmp_path / "out").mkdir()
    [r] = archive([tmp_path / "src"], tmp_path / "out/b.zip", "--hide-names")
    assert inner_files(r.path) == {"src/a/b/": b""}


def test_no_temp_files(src: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp = tmp_path / "tmpdir"
    tmp.mkdir()
    monkeypatch.setenv("TMPDIR", str(tmp))
    archive([src], tmp_path / "out/b.zip", "--hide-names")
    assert os.listdir(tmp) == []
    assert leftovers(tmp_path / "out") == []


def test_corrupt_inner_central_directory_fails(src: Path, tmp_path: Path) -> None:
    """Rebuild a part whose inner central directory lies about a size; it must fail."""
    import hashlib

    [r] = archive([src], tmp_path / "out/b.zip", "--hide-names")
    files = inner_files(r.path)
    records = [_record(n, d, hashlib.sha256(d).digest()) for n, d in files.items()]
    inner_size = len(extract(r.path)["payload.zip"])
    tail = r.inner_tail
    verify_part(r.path, Password(PASSWORD), records, inner=(inner_size, tail))
    wrong = [_record(rec.arcname, b"x" * (rec.size + 1), rec.sha256) for rec in records]
    with pytest.raises(VerifyError):
        verify_part(r.path, Password(PASSWORD), wrong, inner=(inner_size, tail))
    with pytest.raises(VerifyError):
        verify_part(r.path, Password(PASSWORD), records, inner=(inner_size + 1, tail))


def _record(name: str, data: bytes, digest: bytes):  # type: ignore[no-untyped-def]
    from zipseal.write import EntryRecord

    return EntryRecord(name, len(data), name.endswith("/"), digest)


# ── --manifest ───────────────────────────────────────────────────────────────


def test_manifest_in_every_part(tmp_path: Path) -> None:
    src = tmp_path / "src"
    for i in range(10):
        make_tree(src, {f"f{i}.bin": os.urandom(150_000)})
    (tmp_path / "out").mkdir()
    results = archive([src], tmp_path / "out/b.zip", "--manifest", "--max-size", "500KB")
    assert len(results) > 1
    manifests = []
    for n, r in enumerate(results, 1):
        assert r.path.stat().st_size <= 500_000
        files = extract(r.path)
        manifests.append(files.pop("MANIFEST.txt"))
        for name in files:
            assert f"{n:02d}\t{name}\n".encode() in manifests[-1]
    assert len(set(manifests)) == 1
    text = manifests[0].decode()
    assert text.startswith(f"zipseal manifest: 10 entries in {len(results):02d} parts\n")


def test_manifest_inside_inner_zip_with_hide_names(src: Path, tmp_path: Path) -> None:
    [r] = archive([src], tmp_path / "out/b.zip", "--manifest", "--hide-names")
    assert b"MANIFEST" not in r.path.read_bytes()
    assert "MANIFEST.txt" in inner_files(r.path)


@pytest.mark.parametrize("count", [9, 10, 99, 100])
def test_manifest_digit_widths(tmp_path: Path, count: int) -> None:
    src = tmp_path / "src"
    src.mkdir()
    for i in range(count):
        (src / f"名前{i}.txt").write_text(str(i))
    (tmp_path / "out").mkdir()
    [r] = archive([src], tmp_path / "out/b.zip", "--manifest")
    text = extract(r.path)["MANIFEST.txt"].decode()
    width = len(str(count))
    assert text.splitlines()[1].startswith("1".zfill(width) + "\t")


def test_manifest_name_collision(tmp_path: Path) -> None:
    make_tree(tmp_path, {"manifest.TXT": "mine"})
    (tmp_path / "out").mkdir()
    with pytest.raises(InputError, match="already named MANIFEST.txt"):
        archive([tmp_path / "manifest.TXT"], tmp_path / "out/b.zip", "--manifest")


def test_manifest_too_large_for_cap(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    for i in range(300):
        (src / f"{'n' * 150}{i}").write_text("")
    (tmp_path / "out").mkdir()
    with pytest.raises(InputError, match="MANIFEST.txt alone does not fit"):
        archive([src], tmp_path / "out/b.zip", "--manifest", "--max-size", "40KB")


def test_dry_run_counts_parts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from zipseal import cli

    src = tmp_path / "src"
    for i in range(6):
        make_tree(src, {f"f{i}.bin": os.urandom(150_000)})
    code = cli.main([str(src), "-o", str(tmp_path / "b.zip"), "--max-size", "400KB", "--dry-run"])
    assert code == 0
    assert "at most 3 parts of 400,000 bytes" in capsys.readouterr().out
    assert not list(tmp_path.glob("b*"))
