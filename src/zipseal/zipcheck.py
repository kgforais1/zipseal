"""Structural check of a written zip (SPEC.md §6.6).

stream-unzip reads only local entries and stops at the central directory, so a
corrupt central directory or end record would pass decryption. This parser reads
the end records and every central entry, and checks them against the local
headers and data descriptors actually in the file, and against the writer's
records. Any disagreement raises VerifyError.
"""

import os
import struct
from collections.abc import Callable
from dataclasses import dataclass

from zipseal.errors import VerifyError

EOCD_SIG = 0x06054B50
ZIP64_EOCD_SIG = 0x06064B50
ZIP64_LOCATOR_SIG = 0x07064B50
CENTRAL_SIG = 0x02014B50
LOCAL_SIG = 0x04034B50
DESCRIPTOR_SIG = 0x08074B50

EOCD = struct.Struct("<IHHHHIIH")  # 22 bytes
ZIP64_LOCATOR = struct.Struct("<IIQI")  # 20 bytes
ZIP64_EOCD = struct.Struct("<IQHHIIQQQQ")  # 56 bytes
CENTRAL = struct.Struct("<IHHHHHHIIIHHHHHII")  # 46 bytes
LOCAL = struct.Struct("<IHHHHHIIIHH")  # 30 bytes

AES_METHOD = 99
AES_EXTRA_ID = 0x9901
ZIP64_EXTRA_ID = 0x0001
MAX32 = 0xFFFFFFFF
MAX16 = 0xFFFF


@dataclass(frozen=True)
class CentralEntry:
    name: str
    flags: int
    method: int
    crc: int
    compressed: int
    uncompressed: int
    offset: int
    aes: bytes


ReadAt = Callable[[int, int], bytes]


def _extras(blob: bytes, where: str) -> dict[int, bytes]:
    fields: dict[int, bytes] = {}
    pos = 0
    while pos < len(blob):
        if pos + 4 > len(blob):
            raise VerifyError(f"{where}: truncated extra field")
        tag, size = struct.unpack_from("<HH", blob, pos)
        data = blob[pos + 4 : pos + 4 + size]
        if len(data) != size:
            raise VerifyError(f"{where}: truncated extra field")
        if tag in fields:
            raise VerifyError(f"{where}: duplicate extra field {tag:#06x}")
        fields[tag] = data
        pos += 4 + size
    return fields


def _exact(read_at: ReadAt, offset: int, size: int, where: str) -> bytes:
    data = read_at(offset, size)
    if len(data) != size:
        raise VerifyError(f"{where}: unexpected end of file")
    return data


def read_central(read_at: ReadAt, length: int, label: str) -> tuple[list[CentralEntry], int]:
    """Parse the end records and central directory. Return entries and the directory offset."""
    if length < EOCD.size:
        raise VerifyError(f"{label}: too short to be a zip")
    eocd_pos = length - EOCD.size
    sig, disk, cd_disk, n_disk, n_total, cd_size, cd_offset, comment = EOCD.unpack(
        _exact(read_at, eocd_pos, EOCD.size, label)
    )
    if sig != EOCD_SIG or comment != 0:
        raise VerifyError(f"{label}: no end of central directory record at the end")
    # With Zip64 end records, stream-zip sets every 16-bit field to 0xFFFF.
    if disk not in (0, MAX16) or cd_disk not in (0, MAX16) or n_disk != n_total:
        raise VerifyError(f"{label}: multi-disk fields are set")
    end = eocd_pos
    count = n_total
    zip64_used = MAX16 in (disk, cd_disk, n_total) or MAX32 in (cd_size, cd_offset)
    if eocd_pos >= ZIP64_LOCATOR.size:
        loc = ZIP64_LOCATOR.unpack(
            _exact(read_at, eocd_pos - ZIP64_LOCATOR.size, ZIP64_LOCATOR.size, label)
        )
        if loc[0] == ZIP64_LOCATOR_SIG:
            _, loc_disk, z64_pos, disks = loc
            if loc_disk != 0 or disks != 1:
                raise VerifyError(f"{label}: multi-disk Zip64 locator")
            if z64_pos + ZIP64_EOCD.size != eocd_pos - ZIP64_LOCATOR.size:
                raise VerifyError(f"{label}: Zip64 end record is not where the locator says")
            z = ZIP64_EOCD.unpack(_exact(read_at, z64_pos, ZIP64_EOCD.size, label))
            z_sig, z_size, _, _, z_disk, z_cd_disk, z_n_disk, z_n_total, z_cd_size, z_cd_off = z
            if z_sig != ZIP64_EOCD_SIG or z_size != ZIP64_EOCD.size - 12:
                raise VerifyError(f"{label}: malformed Zip64 end record")
            if z_disk != 0 or z_cd_disk != 0 or z_n_disk != z_n_total:
                raise VerifyError(f"{label}: multi-disk Zip64 fields are set")
            for small, big, what in (
                (n_total, z_n_total, "entry count"),
                (cd_size, z_cd_size, "directory size"),
                (cd_offset, z_cd_off, "directory offset"),
            ):
                limit = MAX16 if what == "entry count" else MAX32
                if small != limit and small != big:
                    raise VerifyError(f"{label}: end records disagree on the {what}")
            count, cd_size, cd_offset = z_n_total, z_cd_size, z_cd_off
            end = z64_pos
            zip64_used = False
    if zip64_used:
        raise VerifyError(f"{label}: Zip64 values are needed but no Zip64 end record exists")
    if cd_offset + cd_size != end:
        raise VerifyError(f"{label}: central directory does not end where the end records begin")

    blob = _exact(read_at, cd_offset, cd_size, label)
    entries: list[CentralEntry] = []
    pos = 0
    for i in range(count):
        where = f"{label}: central entry {i + 1}"
        if pos + CENTRAL.size > len(blob):
            raise VerifyError(f"{where}: truncated")
        f = CENTRAL.unpack_from(blob, pos)
        (sig, _, _, flags, method, _, _, crc, comp, uncomp, n_len, x_len, c_len, disk_start,
         _, _, offset) = f  # fmt: skip
        if sig != CENTRAL_SIG:
            raise VerifyError(f"{where}: bad signature")
        if disk_start not in (0, MAX16):
            raise VerifyError(f"{where}: multi-disk entry")
        start = pos + CENTRAL.size
        name_bytes = blob[start : start + n_len]
        extra = _extras(blob[start + n_len : start + n_len + x_len], where)
        pos = start + n_len + x_len + c_len
        if pos > len(blob):
            raise VerifyError(f"{where}: truncated")
        z64 = extra.get(ZIP64_EXTRA_ID, b"")
        values = iter(struct.unpack(f"<{len(z64) // 8}Q", z64[: len(z64) // 8 * 8]))
        try:
            if uncomp == MAX32:
                uncomp = next(values)
            if comp == MAX32:
                comp = next(values)
            if offset == MAX32:
                offset = next(values)
        except StopIteration:
            raise VerifyError(f"{where}: Zip64 extra field is missing values") from None
        try:
            name = name_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise VerifyError(f"{where}: name is not UTF-8") from None
        entries.append(
            CentralEntry(
                name, flags, method, crc, comp, uncomp, offset, extra.get(AES_EXTRA_ID, b"")
            )
        )
    if pos != len(blob):
        raise VerifyError(f"{label}: central directory has {len(blob) - pos} unexplained bytes")
    return entries, cd_offset


def check_locals(read_at: ReadAt, entries: list[CentralEntry], cd_offset: int, label: str) -> None:
    """Check each local header and data descriptor against its central entry.

    Entries must be contiguous: each one ends exactly where the next begins, and
    the last ends where the central directory starts.
    """
    expected_offset = 0
    for c in entries:
        where = f"{label}: {c.name}"
        if c.offset != expected_offset:
            raise VerifyError(f"{where}: local header is not where the central directory says")
        f = LOCAL.unpack(_exact(read_at, c.offset, LOCAL.size, where))
        sig, _, flags, method, _, _, _, _, _, n_len, x_len = f
        if sig != LOCAL_SIG:
            raise VerifyError(f"{where}: bad local header signature")
        head = _exact(read_at, c.offset + LOCAL.size, n_len + x_len, where)
        if head[:n_len].decode("utf-8", "replace") != c.name:
            raise VerifyError(f"{where}: local and central names differ")
        if flags != c.flags or method != c.method:
            raise VerifyError(f"{where}: local and central flags or method differ")
        if _extras(head[n_len:], where).get(AES_EXTRA_ID, b"") != c.aes:
            raise VerifyError(f"{where}: local and central AES fields differ")
        pos = c.offset + LOCAL.size + n_len + x_len + c.compressed
        if flags & 0x08:
            zip64 = ZIP64_EXTRA_ID in _extras(head[n_len:], where)
            fmt = "<IIQQ" if zip64 else "<IIII"
            size = struct.calcsize(fmt)
            d_sig, d_crc, d_comp, d_uncomp = struct.unpack(fmt, _exact(read_at, pos, size, where))
            if d_sig != DESCRIPTOR_SIG:
                raise VerifyError(f"{where}: bad data descriptor")
            if (d_crc, d_comp, d_uncomp) != (c.crc, c.compressed, c.uncompressed):
                raise VerifyError(f"{where}: data descriptor and central directory differ")
            pos += size
        expected_offset = pos
    if expected_offset != cd_offset:
        raise VerifyError(f"{label}: bytes between the last entry and the central directory")


def check_aes_entries(entries: list[CentralEntry], label: str) -> None:
    for c in entries:
        where = f"{label}: {c.name}"
        if not c.flags & 0x01 or c.method != AES_METHOD:
            raise VerifyError(f"{where}: not AES encrypted")
        if len(c.aes) != 7:
            raise VerifyError(f"{where}: malformed AES field")
        vendor_version, vendor, strength, _ = struct.unpack("<H2sBH", c.aes)
        if vendor_version != 2 or vendor != b"AE" or strength != 3:
            raise VerifyError(f"{where}: not AE-2 AES-256")
        if c.crc != 0:
            raise VerifyError(f"{where}: AE-2 entry has a non-zero CRC")


def check_file(fd: int, expected: list[tuple[str, int]], label: str) -> None:
    """Fully check an encrypted part: end records, central entries, locals, AE-2, records.

    `expected` lists (arcname, uncompressed size) in write order.
    """

    def read_at(offset: int, size: int) -> bytes:
        return os.pread(fd, size, offset)

    length = os.fstat(fd).st_size
    entries, cd_offset = read_central(read_at, length, label)
    check_locals(read_at, entries, cd_offset, label)
    check_aes_entries(entries, label)
    found = [(c.name, c.uncompressed) for c in entries]
    if found != expected:
        raise VerifyError(f"{label}: central directory does not list the files that were written")


def check_inner_tail(tail: bytes, length: int, records: list, label: str) -> None:
    """Check an unencrypted inner zip (--hide-names) from its last bytes only.

    The local entries were already checked by stream-unzip, CRCs included, as they
    streamed. This checks the end records and central directory, that entries
    start at 0 in strictly increasing order before the directory, and that names
    and sizes match the writer's records.
    """
    start = length - len(tail)

    def read_at(offset: int, size: int) -> bytes:
        if offset < start:
            raise VerifyError(f"{label}: central directory is larger than expected")
        return tail[offset - start : offset - start + size]

    entries, cd_offset = read_central(read_at, length, label)
    previous = -1
    for c in entries:
        if c.flags & 0x01 or c.method == AES_METHOD:
            raise VerifyError(f"{label}: {c.name}: inner entries must not be encrypted")
        if c.offset <= previous or c.offset >= max(cd_offset, 1):
            raise VerifyError(f"{label}: {c.name}: local header offset is out of order")
        previous = c.offset
    if entries and entries[0].offset != 0:
        raise VerifyError(f"{label}: first entry does not start at offset 0")
    found = [(c.name, c.uncompressed) for c in entries]
    if found != [(r.arcname, r.size) for r in records]:
        raise VerifyError(f"{label}: central directory does not list the files that were written")
