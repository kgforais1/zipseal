"""Splitting under --max-size (SPEC.md §6.2–§6.4)."""

import os
from pathlib import Path

import pytest
from helpers import archive, extract, leftovers
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from zipseal.errors import InputError
from zipseal.write import PartResult


def random_tree(root: Path, sizes: list[int], prefix: str = "f") -> None:
    for i, size in enumerate(sizes):
        p = root / f"{prefix}{i:05d}.bin"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(os.urandom(size))


def check_parts(results: list[PartResult], cap: int, src: Path) -> None:
    seen: dict[str, bytes] = {}
    for r in results:
        assert r.path.stat().st_size <= cap
        files = extract(r.path)  # each part opens on its own
        assert not (files.keys() & seen.keys()), "a file landed in two parts"
        seen.update(files)
    on_disk = {
        f"{src.name}/{p.relative_to(src).as_posix()}": p.read_bytes()
        for p in src.rglob("*")
        if p.is_file()
    }
    assert seen == on_disk


@pytest.mark.parametrize("cap", [1_000_000, 5_000_000])
def test_incompressible_never_exceeds_cap(tmp_path: Path, cap: int) -> None:
    src = tmp_path / "src"
    sizes = [cap // 7, cap // 3, cap // 2, cap // 11, cap // 5] * 3
    random_tree(src, sizes)
    (tmp_path / "out").mkdir()
    results = archive([src], tmp_path / "out/b.zip", "--max-size", str(cap))
    assert len(results) > 1
    check_parts(results, cap, src)
    assert [r.path.name for r in results][0] == f"b-part01-of-{len(results):02d}.zip"
    assert leftovers(tmp_path / "out") == []


@pytest.mark.slow
def test_incompressible_25mb(tmp_path: Path) -> None:
    cap = 25_000_000
    src = tmp_path / "src"
    random_tree(src, [cap // 3, cap // 2, cap // 4, cap // 5, cap // 3, cap // 2])
    (tmp_path / "out").mkdir()
    check_parts(archive([src], tmp_path / "out/b.zip", "--max-size", "25MB"), cap, src)


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(
    sizes=st.lists(st.integers(0, 256 * 1024), min_size=1, max_size=40),
    name_len=st.integers(1, 200),
    cap=st.integers(4 * 1024, 4 * 1024 * 1024),
    order=st.sampled_from(["path", "size"]),
)
def test_property_parts_under_cap(
    tmp_path_factory: pytest.TempPathFactory, sizes: list[int], name_len: int, cap: int, order: str
) -> None:
    base = tmp_path_factory.mktemp("prop")
    src = base / "src"
    src.mkdir()
    for i, size in enumerate(sizes):
        name = f"{i:03d}" + "n" * max(0, name_len - 3)
        (src / name).write_bytes(os.urandom(size))
    (base / "out").mkdir()
    try:
        results = archive([src], base / "out/b.zip", "--max-size", str(cap), "--order", order)
    except InputError:
        assume(False)  # some file cannot fit this cap at all; covered elsewhere
        return
    check_parts(results, cap, src)


def test_compressible_fills_parts(tmp_path: Path) -> None:
    src = tmp_path / "src"
    for i in range(40):
        p = src / f"t{i:02d}.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"line {i}\n" * 20_000)  # ~160 KB, compresses very well
    (tmp_path / "out").mkdir()
    cap = 1_000_000
    results = archive([src], tmp_path / "out/b.zip", "--max-size", str(cap))
    check_parts(results, cap, src)
    for r in results[:-1]:
        assert r.path.stat().st_size >= cap // 2 or len(results) == 1


def test_compressible_bound_slack_is_bounded(tmp_path: Path) -> None:
    """Text compresses far below its bound; parts are still at least half used."""
    src = tmp_path / "src"
    for i in range(30):
        p = src / f"t{i:02d}.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(os.urandom(100_000) + b"a" * 100_000)
    (tmp_path / "out").mkdir()
    cap = 1_500_000
    results = archive([src], tmp_path / "out/b.zip", "--max-size", str(cap))
    check_parts(results, cap, src)
    assert all(r.path.stat().st_size >= cap // 2 for r in results[:-1])


def test_oversized_entry_writes_nothing(tmp_path: Path) -> None:
    src = tmp_path / "src"
    random_tree(src, [10_000, 300_000])
    (tmp_path / "out").mkdir()
    with pytest.raises(InputError, match="cannot fit") as info:
        archive([src], tmp_path / "out/b.zip", "--max-size", "200KB")
    assert "f00001.bin" in str(info.value) and "7zz" in str(info.value)
    assert os.listdir(tmp_path / "out") == []


@pytest.mark.parametrize("order", ["path", "size"])
def test_deterministic(tmp_path: Path, order: str) -> None:
    src = tmp_path / "src"
    random_tree(src, [150_000, 90_000, 300_000, 20_000, 250_000, 10, 0, 180_000])
    layouts = []
    for run in range(2):
        out = tmp_path / f"out{run}"
        out.mkdir()
        results = archive([src], out / "b.zip", "--max-size", "500KB", "--order", order)
        layouts.append([[rec.arcname for rec in r.records] for r in results])
    assert layouts[0] == layouts[1]
    assert len(layouts[0]) > 1


def test_size_order_uses_no_more_parts_than_path(tmp_path: Path) -> None:
    src = tmp_path / "src"
    random_tree(src, [300_000, 50_000, 300_000, 50_000, 300_000, 50_000, 120_000])
    counts = {}
    for order in ("path", "size"):
        out = tmp_path / order
        out.mkdir()
        counts[order] = len(archive([src], out / "b.zip", "--max-size", "500KB", "--order", order))
    assert counts["size"] <= counts["path"]


def test_single_part_keeps_plain_name(tmp_path: Path) -> None:
    src = tmp_path / "src"
    random_tree(src, [1000, 2000])
    (tmp_path / "out").mkdir()
    [r] = archive([src], tmp_path / "out/b.zip", "--max-size", "1MB")
    assert r.path.name == "b.zip"


def test_many_small_files_central_directory(tmp_path: Path) -> None:
    """The central directory of thousands of entries is reserved, not forgotten."""
    src = tmp_path / "src"
    src.mkdir()
    for i in range(5000):
        (src / f"empty-file-with-a-longish-name-{i:05d}.txt").write_bytes(b"")
    (tmp_path / "out").mkdir()
    cap = 1_000_000
    results = archive([src], tmp_path / "out/b.zip", "--max-size", str(cap))
    assert len(results) > 1
    for r in results:
        assert r.path.stat().st_size <= cap
    assert sum(len(r.records) for r in results) == 5000


def test_empty_input_writes_empty_archive(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (tmp_path / "out").mkdir()
    [r] = archive([src], tmp_path / "out/b.zip", "--max-size", "1MB")
    assert extract(r.path) == {"src/": b""}


@pytest.mark.slow
@pytest.mark.parametrize("kind", ["files", "dirs", "mixed"])
@pytest.mark.parametrize("count", [65_535, 65_536])
def test_entry_count_limit(tmp_path: Path, kind: str, count: int) -> None:
    import zipfile

    src = tmp_path / "src"
    src.mkdir()
    for i in range(count - 1):  # plus the src/ folder itself only when it is empty
        is_dir = kind == "dirs" or (kind == "mixed" and i % 2)
        p = src / f"e{i:06d}"
        if is_dir:
            p.mkdir()
        else:
            p.write_bytes(b"")
    (src / "last").write_bytes(b"x")
    (tmp_path / "out").mkdir()
    [r] = archive([src], tmp_path / "out/b.zip")
    with zipfile.ZipFile(r.path) as zf:
        assert len(zf.infolist()) == count


@pytest.mark.slow
def test_file_over_4gib_uses_zip64(tmp_path: Path) -> None:
    import zipfile

    src = tmp_path / "src"
    src.mkdir()
    big = src / "big.bin"
    with open(big, "wb") as fh:  # sparse: fast to create, compresses to almost nothing
        fh.truncate(4 * 2**30 + 12345)
    (src / "small.txt").write_text("small")
    (tmp_path / "out").mkdir()
    [r] = archive([src], tmp_path / "out/b.zip")
    with zipfile.ZipFile(r.path) as zf:
        sizes = {i.filename: i.file_size for i in zf.infolist()}
    assert sizes["src/big.bin"] == 4 * 2**30 + 12345
    assert sizes["src/small.txt"] == 5


@pytest.mark.slow
def test_ten_thousand_small_files(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    for i in range(10_000):
        (src / f"f{i:05d}.txt").write_text(str(i))
    (tmp_path / "out").mkdir()
    results = archive([src], tmp_path / "out/b.zip", "--max-size", "500KB")
    assert sum(len(r.records) for r in results) == 10_000
    assert all(r.path.stat().st_size <= 500_000 for r in results)
