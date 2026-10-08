"""Interop with 7-Zip (SPEC.md §8). Skipped when 7zz is not installed."""

import os
import subprocess
from pathlib import Path

import pytest
from helpers import PASSWORD, archive, make_tree

pytestmark = pytest.mark.sevenzip


def sevenzip(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["7zz", *args], capture_output=True, text=True)


@pytest.fixture
def src(tmp_path: Path) -> Path:
    s = tmp_path / "src"
    make_tree(
        s,
        {
            "a.txt": "hello\n",
            "empty/": "",
            "zero.txt": "",
            "café/日本.txt": "unicode",
            **{f"bin/f{i}.bin": os.urandom(120_000) for i in range(8)},
        },
    )
    (tmp_path / "out").mkdir()
    return s


def extract_all(part: Path, dest: Path, password: str = PASSWORD) -> None:
    proc = sevenzip("x", "-y", f"-p{password}", f"-o{dest}", str(part))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def same_tree(a: Path, b: Path) -> None:
    files_a = {p.relative_to(a): p.read_bytes() for p in a.rglob("*") if p.is_file()}
    files_b = {p.relative_to(b): p.read_bytes() for p in b.rglob("*") if p.is_file()}
    assert files_a == files_b


@pytest.mark.parametrize("pw", [PASSWORD, "pässwörd-日本語"])
def test_7zz_tests_and_extracts_single(src: Path, tmp_path: Path, pw: str) -> None:
    [r] = archive([src], tmp_path / "out/b.zip", password=pw)
    proc = sevenzip("t", f"-p{pw}", str(r.path))
    assert proc.returncode == 0 and "Everything is Ok" in proc.stdout, proc.stdout
    extract_all(r.path, tmp_path / "x", pw)
    same_tree(src, tmp_path / "x/src")
    assert (tmp_path / "x/src/empty").is_dir()


def test_7zz_rejects_wrong_password(src: Path, tmp_path: Path) -> None:
    [r] = archive([src], tmp_path / "out/b.zip")
    assert sevenzip("t", "-pwrong-password", str(r.path)).returncode != 0


def test_7zz_each_part_alone(src: Path, tmp_path: Path) -> None:
    results = archive([src], tmp_path / "out/b.zip", "--max-size", "300KB")
    assert len(results) > 1
    dest = tmp_path / "x"
    for r in results:
        proc = sevenzip("t", f"-p{PASSWORD}", str(r.path))
        assert proc.returncode == 0, proc.stdout
        extract_all(r.path, dest)  # each part on its own, into one folder
    same_tree(src, dest / "src")


def test_7zz_hide_names(src: Path, tmp_path: Path) -> None:
    results = archive([src], tmp_path / "out/b.zip", "--max-size", "300KB", "--hide-names")
    dest = tmp_path / "x"
    for i, r in enumerate(results):
        listing = sevenzip("l", "-slt", str(r.path)).stdout
        paths = [ln[7:] for ln in listing.splitlines() if ln.startswith("Path = ")]
        assert paths[1:] == ["payload.zip"]  # paths[0] is the archive itself
        outer = tmp_path / f"outer{i}"
        extract_all(r.path, outer)
        proc = sevenzip("x", "-y", f"-o{dest}", str(outer / "payload.zip"))
        assert proc.returncode == 0, proc.stdout
    same_tree(src, dest / "src")


@pytest.mark.slow
def test_7zz_zip64_entry_count(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    for i in range(65_536):
        (src / f"e{i:06d}").write_bytes(b"")
    (tmp_path / "out").mkdir()
    [r] = archive([src], tmp_path / "out/b.zip")
    proc = sevenzip("t", f"-p{PASSWORD}", str(r.path))
    assert proc.returncode == 0 and "Files: 65536" in proc.stdout, proc.stdout[-500:]
