import io
import os
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import pytest

from zipseal.collect import DOS_MAX, DOS_MIN, Collection, collect
from zipseal.errors import InputError

DEFAULT_EXCLUDES = [".DS_Store", "._*", "Thumbs.db"]


def run(
    paths: list[Path],
    tmp_path: Path,
    *,
    excludes: list[str] | None = None,
    follow: bool = False,
    output: Path | None = None,
) -> tuple[Collection, str]:
    warn = io.StringIO()
    c = collect(
        paths,
        excludes=DEFAULT_EXCLUDES if excludes is None else excludes,
        follow_symlinks=follow,
        output=output or tmp_path / "out" / "bundle.zip",
        warn=warn,
    )
    return c, warn.getvalue()


def names(c: Collection) -> list[str]:
    return [e.arcname for e in c.entries]


def make(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def test_folder_keeps_top_name_and_file_goes_to_root(tmp_path: Path) -> None:
    make(tmp_path, {"reports/q3.txt": "a", "reports/sub/deep.txt": "bb", "notes.txt": "c"})
    with run([tmp_path / "reports", tmp_path / "notes.txt"], tmp_path)[0] as c:
        assert names(c) == ["notes.txt", "reports/q3.txt", "reports/sub/deep.txt"]
        deep = c.entries[2]
        assert deep.relparts == ("reports", "sub", "deep.txt")
        assert deep.size == 2
        assert len(deep.chain) == 3
        assert deep.chain[-1] == (
            os.stat(tmp_path / "reports/sub/deep.txt").st_dev,
            os.stat(tmp_path / "reports/sub/deep.txt").st_ino,
        )


def test_relative_and_dot_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make(tmp_path, {"proj/a.txt": "a"})
    monkeypatch.chdir(tmp_path / "proj")
    with run([Path(".")], tmp_path)[0] as c:
        assert names(c) == ["proj/a.txt"]


def test_default_and_custom_excludes(tmp_path: Path) -> None:
    make(
        tmp_path,
        {
            "d/.DS_Store": "",
            "d/._a.txt": "",
            "d/Thumbs.db": "",
            "d/a.txt": "",
            "d/b.tmp": "",
            "d/cache/x.txt": "",
            "d/keep/cache/y.txt": "",
        },
    )
    with run([tmp_path / "d"], tmp_path, excludes=[*DEFAULT_EXCLUDES, "*.tmp", "d/cache"])[0] as c:
        assert names(c) == ["d/a.txt", "d/keep/cache/y.txt"]
    with run([tmp_path / "d"], tmp_path, excludes=[])[0] as c:
        assert "d/.DS_Store" in names(c) and "d/b.tmp" in names(c)


def test_empty_folders_are_entries(tmp_path: Path) -> None:
    (tmp_path / "d/empty").mkdir(parents=True)
    (tmp_path / "d/only-junk").mkdir()
    (tmp_path / "d/only-junk/.DS_Store").write_text("")
    (tmp_path / "d/full").mkdir()
    (tmp_path / "d/full/f.txt").write_text("x")
    (tmp_path / "e").write_text("")
    with run([tmp_path / "d", tmp_path / "e"], tmp_path)[0] as c:
        assert names(c) == ["d/empty/", "d/full/f.txt", "d/only-junk/", "e"]
        empty = c.entries[0]
        assert empty.is_dir and empty.size == 0
    (tmp_path / "solo").mkdir()
    with run([tmp_path / "solo"], tmp_path)[0] as c:
        assert names(c) == ["solo/"]


def test_symlinks_skipped_by_default(tmp_path: Path) -> None:
    make(tmp_path, {"d/real.txt": "x", "elsewhere/t.txt": "y"})
    (tmp_path / "d/link.txt").symlink_to(tmp_path / "d/real.txt")
    (tmp_path / "d/linkdir").symlink_to(tmp_path / "elsewhere")
    (tmp_path / "rootlink").symlink_to(tmp_path / "elsewhere")
    c, warn = run([tmp_path / "d", tmp_path / "rootlink"], tmp_path)
    with c:
        assert names(c) == ["d/real.txt"]
    assert warn.count("skipping symlink") == 3


def test_symlinks_followed(tmp_path: Path) -> None:
    make(tmp_path, {"d/real.txt": "x", "elsewhere/t.txt": "y"})
    (tmp_path / "d/link.txt").symlink_to(tmp_path / "d/real.txt")
    (tmp_path / "d/linkdir").symlink_to(tmp_path / "elsewhere")
    (tmp_path / "rootlink").symlink_to(tmp_path / "elsewhere")
    with run([tmp_path / "d", tmp_path / "rootlink"], tmp_path, follow=True)[0] as c:
        assert names(c) == ["d/link.txt", "d/linkdir/t.txt", "d/real.txt", "rootlink/t.txt"]


def test_symlink_cycle_fails(tmp_path: Path) -> None:
    make(tmp_path, {"d/sub/a.txt": "x"})
    (tmp_path / "d/sub/back").symlink_to(tmp_path / "d")
    with pytest.raises(InputError, match="cycle"):
        run([tmp_path / "d"], tmp_path, follow=True)


def test_special_files_skipped(tmp_path: Path) -> None:
    make(tmp_path, {"d/a.txt": "x"})
    os.mkfifo(tmp_path / "d/pipe")
    c, warn = run([tmp_path / "d"], tmp_path)
    with c:
        assert names(c) == ["d/a.txt"]
    assert "special file" in warn


def test_missing_input(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="no such file"):
        run([tmp_path / "nope"], tmp_path)


def test_collision_same_path(tmp_path: Path) -> None:
    make(tmp_path, {"a/x.txt": "1", "b/x.txt": "2"})
    with pytest.raises(InputError, match=r"x\.txt \(same path, 2 sources\)"):
        run([tmp_path / "a/x.txt", tmp_path / "b/x.txt"], tmp_path)


def test_collision_case_only(tmp_path: Path) -> None:
    make(tmp_path, {"a/Readme.txt": "1", "b/README.TXT": "2"})
    with pytest.raises(InputError, match="differ only in case"):
        run([tmp_path / "a/Readme.txt", tmp_path / "b/README.TXT"], tmp_path)


def test_collision_casefold_eszett(tmp_path: Path) -> None:
    make(tmp_path, {"a/straße.txt": "1", "b/STRASSE.txt": "2"})
    with pytest.raises(InputError, match="differ only in case"):
        run([tmp_path / "a/straße.txt", tmp_path / "b/STRASSE.txt"], tmp_path)


def test_unicode_names_normalized_to_nfc(tmp_path: Path) -> None:
    nfd = unicodedata.normalize("NFD", "café.txt")
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / nfd).write_text("x")
    (tmp_path / "d/日本.txt").write_text("y")
    with run([tmp_path / "d"], tmp_path)[0] as c:
        assert names(c) == ["d/café.txt", "d/日本.txt"]
        assert names(c)[0] == unicodedata.normalize("NFC", "d/café.txt")


def test_output_inside_input_is_skipped(tmp_path: Path) -> None:
    make(
        tmp_path,
        {
            "d/a.txt": "x",
            "d/bundle.zip": "old",
            "d/bundle-part01-of-02.zip": "old",
            "d/bundle-part01.zip.partial": "tmp",
            "d/bundle-party.zip": "keep",
            "d/sub/bundle.zip": "keep, different folder",
        },
    )
    with run([tmp_path / "d"], tmp_path, output=tmp_path / "d/bundle.zip")[0] as c:
        assert names(c) == ["d/a.txt", "d/bundle-party.zip", "d/sub/bundle.zip"]


def test_timestamps_clamped(tmp_path: Path) -> None:
    make(tmp_path, {"d/old.txt": "", "d/new.txt": "", "d/y2038.txt": "", "d/ok.txt": ""})
    os.utime(tmp_path / "d/old.txt", (0, 0))  # 1970
    far = datetime(2200, 1, 1).timestamp()
    os.utime(tmp_path / "d/new.txt", (far, far))
    y2038 = datetime(2038, 1, 20).timestamp()
    os.utime(tmp_path / "d/y2038.txt", (y2038, y2038))
    c, warn = run([tmp_path / "d"], tmp_path)
    with c:
        by = {e.arcname: e for e in c.entries}
        assert by["d/old.txt"].mtime == DOS_MIN
        assert by["d/new.txt"].mtime == DOS_MAX
        assert by["d/y2038.txt"].mtime == datetime(2038, 1, 20)
    assert warn.count("outside the zip range") == 2


def test_permission_bits_and_order(tmp_path: Path) -> None:
    make(tmp_path, {"d/b.sh": "", "d/a.txt": ""})
    (tmp_path / "d/b.sh").chmod(0o755)
    with run([tmp_path / "d"], tmp_path)[0] as c:
        assert names(c) == ["d/a.txt", "d/b.sh"]
        assert c.entries[1].mode == 0o755


def test_roots_closed(tmp_path: Path) -> None:
    make(tmp_path, {"d/a.txt": ""})
    c, _ = run([tmp_path / "d"], tmp_path)
    fds = list(c.roots)
    c.close()
    for fd in fds:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.skipif(sys.platform == "darwin", reason="APFS rejects non-UTF-8 names")
def test_undecodable_names(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir()
    (d / os.fsdecode(b"bad\xff.txt")).write_text("x")
    with pytest.raises(InputError, match="not valid UTF-8"):
        run([d], tmp_path)
