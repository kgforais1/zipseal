"""Corrupt one structure at a time; verification must catch every one (SPEC.md §6.6)."""

import hashlib
import struct
from collections.abc import Callable
from pathlib import Path

import pytest
from helpers import PASSWORD, archive, extract, make_tree

from zipseal.errors import VerifyError
from zipseal.passwords import Password
from zipseal.verify import verify_part
from zipseal.write import EntryRecord
from zipseal.zipcheck import CENTRAL, CENTRAL_SIG, EOCD, ZIP64_EOCD, ZIP64_EOCD_SIG

Mutation = Callable[[bytearray], None]


@pytest.fixture
def part(tmp_path: Path) -> tuple[Path, list[EntryRecord]]:
    make_tree(tmp_path / "src", {"a.txt": "alpha" * 100, "b.txt": "bravo" * 50, "d/": ""})
    (tmp_path / "out").mkdir()
    out = tmp_path / "out/p.zip"
    archive([tmp_path / "src"], out)
    records = [
        EntryRecord(n, len(d), n.endswith("/"), hashlib.sha256(d).digest())
        for n, d in extract(out).items()
    ]
    return out, records


def central_offsets(data: bytes) -> list[int]:
    eocd = len(data) - EOCD.size
    *_, cd_size, cd_offset, _ = EOCD.unpack_from(data, eocd)
    offsets, pos = [], cd_offset
    while pos < cd_offset + cd_size:
        assert struct.unpack_from("<I", data, pos)[0] == CENTRAL_SIG
        f = CENTRAL.unpack_from(data, pos)
        offsets.append(pos)
        pos += CENTRAL.size + f[10] + f[11] + f[12]
    return offsets


def set_central(field: int, value: int, entry: int = 0) -> Mutation:
    """Overwrite one field of a central entry. Field offsets follow the CENTRAL struct."""
    layout = {"flags": (8, "<H"), "method": (10, "<H"), "crc": (16, "<I"),
              "comp": (20, "<I"), "uncomp": (24, "<I"), "offset": (42, "<I")}  # fmt: skip
    del layout  # documented above; the callers pass the byte offset directly

    def mutate(data: bytearray) -> None:
        pos = central_offsets(bytes(data))[entry] + field
        width = 2 if field in (8, 10) else 4
        data[pos : pos + width] = value.to_bytes(width, "little")

    return mutate


def truncate_end(data: bytearray) -> None:
    del data[-10:]


def junk_central(data: bytearray) -> None:
    pos = central_offsets(bytes(data))[0]
    data[pos : pos + 40] = b"\xaa" * 40


def eocd_count(data: bytearray) -> None:
    eocd = len(data) - EOCD.size
    data[eocd + 10 : eocd + 12] = (99).to_bytes(2, "little")


def cd_offset_past_end(data: bytearray) -> None:
    eocd = len(data) - EOCD.size
    data[eocd + 16 : eocd + 20] = (len(data) + 100).to_bytes(4, "little")


def aes_vendor_version(data: bytearray) -> None:
    """Turn the first central entry into AE-1."""
    pos = central_offsets(bytes(data))[0]
    i = data.index(b"\x01\x99\x07\x00\x02\x00AE", pos)
    data[i + 4 : i + 6] = (1).to_bytes(2, "little")


MUTATIONS: dict[str, Mutation] = {
    "truncated end record": truncate_end,
    "junk central directory": junk_central,
    "eocd entry count": eocd_count,
    "directory offset past end": cd_offset_past_end,
    "central compressed size": set_central(20, 12345),
    "central uncompressed size": set_central(24, 7),
    "central crc": set_central(16, 0xDEADBEEF),
    "central method": set_central(10, 8),
    "central flags": set_central(8, 0x0808),
    "central local offset": set_central(42, 3),
    "second entry offset": set_central(42, 0, entry=1),
    "central aes extra": aes_vendor_version,
}


@pytest.mark.parametrize("name", list(MUTATIONS))
def test_mutation_fails_verification(name: str, part: tuple[Path, list[EntryRecord]]) -> None:
    path, records = part
    verify_part(path, Password(PASSWORD), records)  # unmutated part passes
    data = bytearray(path.read_bytes())
    MUTATIONS[name](data)
    path.write_bytes(bytes(data))
    with pytest.raises(VerifyError):
        verify_part(path, Password(PASSWORD), records)


def test_records_must_match(part: tuple[Path, list[EntryRecord]]) -> None:
    path, records = part
    wrong = [EntryRecord(r.arcname, r.size + 1, r.is_dir, r.sha256) for r in records]
    with pytest.raises(VerifyError, match="does not list the files"):
        verify_part(path, Password(PASSWORD), wrong)


def test_zip64_end_records_checked(tmp_path: Path) -> None:
    """A part with 64-bit entries has Zip64 end records; disagreeing counts are caught."""
    from zipseal import plan

    make_tree(tmp_path / "src", {"a.txt": "x"})
    (tmp_path / "out").mkdir()
    out = tmp_path / "out/p.zip"
    original = plan.ZIP64_FROM_INDEX
    plan.ZIP64_FROM_INDEX = 0
    try:
        archive([tmp_path / "src"], out)
    finally:
        plan.ZIP64_FROM_INDEX = original
    data = bytearray(out.read_bytes())
    z64 = data.rindex(struct.pack("<I", ZIP64_EOCD_SIG))
    assert z64 + ZIP64_EOCD.size + 20 + EOCD.size == len(data)
    records = [EntryRecord("src/a.txt", 1, False, hashlib.sha256(b"x").digest())]
    verify_part(out, Password(PASSWORD), records)
    # Both Zip64 entry counts (this disk, total) set to 5: still caught.
    data[z64 + 24 : z64 + 40] = (5).to_bytes(8, "little") * 2
    out.write_bytes(bytes(data))
    with pytest.raises(VerifyError):
        verify_part(out, Password(PASSWORD), records)
