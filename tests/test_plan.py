"""The bounds in plan.py must match what stream-zip writes (SPEC.md §6.2)."""

import os
import stat
import zipfile
import zlib
from datetime import datetime
from io import BytesIO

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from stream_zip import NO_COMPRESSION_32, NO_COMPRESSION_64, ZIP_32, ZIP_64, stream_zip

from zipseal import plan
from zipseal.collect import FileEntry
from zipseal.write import compressor_factory


def entry(name: str, size: int, is_dir: bool = False) -> FileEntry:
    return FileEntry(0, (name,), name, size, datetime(2026, 1, 1), 0o644, is_dir, ((0, 0),))


def build(e: FileEntry, data: bytes, zip64: bool, level: int = 6) -> bytes:
    if e.is_dir:
        method = NO_COMPRESSION_64(0, 0) if zip64 else NO_COMPRESSION_32(0, 0)
        mode, chunks = stat.S_IFDIR | 0o755, ()
    else:
        method = ZIP_64 if zip64 else ZIP_32
        mode, chunks = stat.S_IFREG | 0o644, (data,)
    return b"".join(
        stream_zip(
            [(e.arcname, e.mtime, mode, method, chunks)],
            get_compressobj=compressor_factory(level),
            extended_timestamps=False,
            password="pw",
        )
    )


@pytest.mark.parametrize("zip64", [False, True])
@pytest.mark.parametrize(
    ("name", "size", "is_dir"),
    [
        ("a", 0, False),
        ("dir/", 0, True),
        ("名前/ファイル.bin", 70_000, False),
        ("x" * 200, 1, False),
    ],
)
def test_framing_is_exact(name: str, size: int, is_dir: bool, zip64: bool) -> None:
    """Measured local framing equals the model; the central entry size is exact."""
    e = entry(name, size, is_dir)
    data = os.urandom(size)
    z = build(e, data, zip64)
    with zipfile.ZipFile(BytesIO(z)) as zf:
        info = zf.infolist()[0]
        cd_start = zf.start_dir
    compressed_payload = info.compress_size - plan.AES_OVERHEAD
    framing = cd_start - compressed_payload
    assert framing == plan.local_header(e, zip64) + plan.AES_OVERHEAD + plan.descriptor(e, zip64)
    end = 98 if zip64 else 22
    assert len(z) - cd_start == plan.central_size(e, zip64) + end
    assert cd_start <= plan.local_bound(e, zip64)
    assert len(z) <= plan.local_bound(e, zip64) + plan.central_size(e, zip64) + plan.END_RECORDS


@settings(max_examples=150, deadline=None)
@given(
    size=st.one_of(
        st.integers(0, 4096),
        st.sampled_from([16383, 16384, 16385, 65535, 65536, 65537, 1 << 20]),
        st.integers(0, 2_000_000),
    ),
    level=st.integers(0, 9),
    feed=st.sampled_from([1, 7, 512, 4096, 16384, 65536, 1 << 20]),
    compressible=st.booleans(),
)
def test_deflate_bound_holds(size: int, level: int, feed: int, compressible: bool) -> None:
    data = (b"abc" * (size // 3 + 1))[:size] if compressible else os.urandom(size)
    if feed == 1 and size > 20_000:
        feed = 512  # keep the test fast
    c = zlib.compressobj(level, zlib.DEFLATED, -zlib.MAX_WBITS, 8)
    out = sum(len(c.compress(data[i : i + feed])) for i in range(0, size, feed))
    out += len(c.flush())
    assert out <= plan.deflate_bound(size)


def test_zip64_choice() -> None:
    e = entry("a", 10)
    assert not plan.cost(e, index=0, offset=0, central_so_far=0).zip64
    assert plan.cost(e, index=plan.ZIP64_FROM_INDEX, offset=0, central_so_far=0).zip64
    assert plan.cost(e, index=0, offset=plan.ZIP32_LIMIT - 50, central_so_far=0).zip64
    assert plan.cost(e, index=0, offset=0, central_so_far=plan.ZIP32_LIMIT - 10).zip64
    assert plan.cost(entry("big", 5 * 2**30), index=0, offset=0, central_so_far=0).zip64
