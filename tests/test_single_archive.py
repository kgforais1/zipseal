import io
import os
import stat
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

import pytest
from helpers import BSDTAR, PASSWORD, archive, args_for, collect_for, extract, leftovers, make_tree

from zipseal.errors import VerifyError, WriteError
from zipseal.passwords import Password
from zipseal.pipeline import write_archive
from zipseal.verify import verify_part
from zipseal.write import EntryRecord


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    make_tree(
        src,
        {
            "a.txt": "hello\n",
            "sub/r.bin": os.urandom(200_000),
            "sub/text.txt": "line\n" * 5000,
            "empty/": "",
            "zero.txt": "",
            "café/日本.txt": "unicode",
        },
    )
    (tmp_path / "out").mkdir()
    return src


def records_of(path: Path, password: str = PASSWORD) -> list[EntryRecord]:
    import hashlib

    recs = []
    for name, data in extract(path, password).items():
        recs.append(EntryRecord(name, len(data), name.endswith("/"), hashlib.sha256(data).digest()))
    return recs


def test_round_trip(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "out/bundle.zip"
    [result] = archive([tree], out)
    assert result.path == out
    files = extract(out)
    assert files["src/a.txt"] == b"hello\n"
    assert files["src/sub/r.bin"] == (tree / "sub/r.bin").read_bytes()
    assert files["src/sub/text.txt"] == (tree / "sub/text.txt").read_bytes()
    assert files["src/empty/"] == b""
    assert files["src/zero.txt"] == b""
    assert files["src/café/日本.txt"] == b"unicode"
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert leftovers(out.parent) == []


def test_zipfile_cross_check(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "out/bundle.zip"
    archive([tree], out)
    with zipfile.ZipFile(out) as zf:
        infos = zf.infolist()
    assert {i.filename for i in infos} == set(extract(out))
    assert all(i.compress_type == 99 and i.flag_bits & 1 for i in infos)


@pytest.mark.skipif(BSDTAR is None, reason="no libarchive tar (bsdtar)")
def test_libarchive_extracts(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "out/bundle.zip"
    archive([tree], out)
    dest = tmp_path / "x"
    dest.mkdir()
    proc = subprocess.run(
        [str(BSDTAR), "-xf", str(out), "-C", str(dest), "--passphrase", PASSWORD],
        capture_output=True,
    )
    if proc.returncode != 0 and b"passphrase" in proc.stderr:
        pytest.skip("this tar has no --passphrase support")
    assert proc.returncode == 0, proc.stderr
    assert (dest / "src/sub/r.bin").read_bytes() == (tree / "sub/r.bin").read_bytes()


def test_non_ascii_password(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "out/bundle.zip"
    archive([tree], out, password="pässwörd-ünïcode")
    assert extract(out, "pässwörd-ünïcode")["src/a.txt"] == b"hello\n"


def test_wrong_password_fails_verification(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "out/bundle.zip"
    archive([tree], out)
    with pytest.raises(VerifyError, match="failed to decrypt"):
        verify_part(out, Password("wrong-password-here"), records_of(out))


def test_corrupt_ciphertext_fails(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "out/bundle.zip"
    archive([tree], out)
    recs = records_of(out)
    data = bytearray(out.read_bytes())
    data[5000] ^= 0x01  # inside src/sub/r.bin's encrypted data
    out.write_bytes(bytes(data))
    with pytest.raises(VerifyError):
        verify_part(out, Password(PASSWORD), recs)


def test_existing_output_refused(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "out/bundle.zip"
    out.write_text("precious")
    with pytest.raises(WriteError, match="already exist"):
        archive([tree], out)
    assert out.read_text() == "precious"
    (tmp_path / "out/bundle-part01-of-02.zip").write_text("old part")
    out.unlink()
    with pytest.raises(WriteError, match="already exist"):
        archive([tree], out)


def test_force_replaces(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "out/bundle.zip"
    out.write_text("old")
    archive([tree], out, "--force")
    assert extract(out)["src/a.txt"] == b"hello\n"
    assert leftovers(out.parent) == []


def test_growing_file_fails(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "out/bundle.zip"
    args = args_for([tree], out)
    with collect_for(args) as c:
        with open(tree / "a.txt", "a") as fh:
            fh.write("more")
        with pytest.raises(WriteError, match="file size changed"):
            write_archive(args, c, lambda _: Password(PASSWORD), err=io.StringIO())
    assert not out.exists()
    assert leftovers(out.parent) == []


def test_shrinking_file_fails(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "out/bundle.zip"
    args = args_for([tree], out)
    with collect_for(args) as c:
        (tree / "sub/text.txt").write_text("short")
        with pytest.raises(WriteError, match="file size changed"):
            write_archive(args, c, lambda _: Password(PASSWORD), err=io.StringIO())
    assert leftovers(out.parent) == []


def test_file_swapped_for_symlink_fails(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "out/bundle.zip"
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET")  # same size as "hello\n"
    args = args_for([tree], out)
    with collect_for(args) as c:
        (tree / "a.txt").unlink()
        (tree / "a.txt").symlink_to(secret)
        with pytest.raises(WriteError, match="changed since it was collected"):
            write_archive(args, c, lambda _: Password(PASSWORD), err=io.StringIO())
    assert not out.exists()


def test_parent_folder_swapped_fails(tree: Path, tmp_path: Path) -> None:
    """A swapped folder holding a hard link to the original file is still refused."""
    out = tmp_path / "out/bundle.zip"
    args = args_for([tree], out)
    with collect_for(args) as c:
        (tree / "sub").rename(tmp_path / "old-sub")
        (tree / "sub").mkdir()
        for name in ("r.bin", "text.txt"):
            os.link(tmp_path / "old-sub" / name, tree / "sub" / name)
        with pytest.raises(WriteError, match="a folder above it changed"):
            write_archive(args, c, lambda _: Password(PASSWORD), err=io.StringIO())


def test_file_swapped_for_fifo_fails_fast(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "out/bundle.zip"
    args = args_for([tree], out)
    errors: list[BaseException] = []
    with collect_for(args) as c:
        (tree / "a.txt").unlink()
        os.mkfifo(tree / "a.txt")

        def go() -> None:
            try:
                write_archive(args, c, lambda _: Password(PASSWORD), err=io.StringIO())
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        t = threading.Thread(target=go, daemon=True)
        t.start()
        t.join(5)
        assert not t.is_alive(), "opening a FIFO blocked"
    assert errors and isinstance(errors[0], WriteError)


def test_planted_partial_symlink_not_followed(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "out/bundle.zip"
    victim = tmp_path / "victim.txt"
    victim.write_text("do not touch")
    (tmp_path / "out/bundle-part01.zip.partial").symlink_to(victim)
    with pytest.raises(WriteError, match="refusing to write through"):
        archive([tree], out)
    assert victim.read_text() == "do not touch"


def test_final_name_appearing_mid_run_not_overwritten(
    tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out/bundle.zip"
    import zipseal.pipeline as pipeline

    real_verify = pipeline.verify_part

    def verify_then_race(*a, **kw):  # type: ignore[no-untyped-def]
        real_verify(*a, **kw)
        out.write_text("someone else's file")

    monkeypatch.setattr(pipeline, "verify_part", verify_then_race)
    with pytest.raises(WriteError, match="appeared while zipseal was running"):
        archive([tree], out)
    assert out.read_text() == "someone else's file"
    assert leftovers(out.parent) == []


def test_symlinked_root_and_folder_followed(tmp_path: Path) -> None:
    make_tree(tmp_path, {"real/a.txt": "a", "other/b.txt": "b"})
    (tmp_path / "real/linked").symlink_to(tmp_path / "other")
    (tmp_path / "rootlink").symlink_to(tmp_path / "real")
    (tmp_path / "out").mkdir()
    out = tmp_path / "out/bundle.zip"
    archive([tmp_path / "rootlink"], out, "--follow-symlinks")
    assert extract(out) == {"rootlink/a.txt": b"a", "rootlink/linked/b.txt": b"b"}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX only")
def test_interrupt_cleans_partials(
    tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out/bundle.zip"
    import zipseal.pipeline as pipeline

    def boom(*a, **kw):  # type: ignore[no-untyped-def]
        raise KeyboardInterrupt

    monkeypatch.setattr(pipeline, "verify_part", boom)
    with pytest.raises(KeyboardInterrupt):
        archive([tree], out)
    assert leftovers(out.parent) == []
    assert not out.exists()


@pytest.mark.skipif(BSDTAR is None, reason="no libarchive tar (bsdtar)")
@pytest.mark.parametrize("pw", ["pässwörd-ünïcode", "密码-password-日本語"])
def test_non_ascii_password_interop(tree: Path, tmp_path: Path, pw: str) -> None:
    """libarchive derives the key from UTF-8 bytes, as 7-Zip does."""
    out = tmp_path / "out/bundle.zip"
    archive([tree], out, password=pw)
    dest = tmp_path / "x"
    dest.mkdir()
    proc = subprocess.run(
        [str(BSDTAR), "-xf", str(out), "-C", str(dest), "--passphrase", pw], capture_output=True
    )
    assert proc.returncode == 0, proc.stderr
    assert (dest / "src/a.txt").read_text() == "hello\n"
