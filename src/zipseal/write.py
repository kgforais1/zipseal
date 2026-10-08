"""Stream entries into one encrypted part (SPEC.md §6.2, §6.5).

Methods are always explicit (never ZIP_AUTO), so the caller's compressor is used
and the bounds in plan.py apply.
"""

import hashlib
import os
import stat
import zlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from stream_zip import NO_COMPRESSION_32, NO_COMPRESSION_64, ZIP_32, ZIP_64, stream_zip

from zipseal.collect import Collection, FileEntry
from zipseal.errors import WriteError
from zipseal.passwords import Password
from zipseal.sources import read_chunks

OUTPUT_CHUNK = 1 << 16


@dataclass
class EntryRecord:
    arcname: str
    size: int
    is_dir: bool
    sha256: bytes = b""


@dataclass
class PartResult:
    path: Path
    size: int = 0
    records: list[EntryRecord] = field(default_factory=list)


def compressor_factory(level: int) -> Callable[[], "zlib._Compress"]:
    """Raw deflate with memLevel 8: the configuration deflate_bound() assumes."""

    def make() -> "zlib._Compress":
        return zlib.compressobj(level, zlib.DEFLATED, -zlib.MAX_WBITS, 8)

    return make


def _members(
    collection: Collection,
    entries: Iterable[tuple[FileEntry, bool]],
    records: list[EntryRecord],
) -> Iterator[tuple]:
    for entry, zip64 in entries:
        if entry.is_dir:
            method = NO_COMPRESSION_64(0, 0) if zip64 else NO_COMPRESSION_32(0, 0)
            records.append(EntryRecord(entry.arcname, 0, True, hashlib.sha256().digest()))
            yield entry.arcname, entry.mtime, stat.S_IFDIR | entry.mode, method, ()
            continue
        digest = hashlib.sha256()
        record = EntryRecord(entry.arcname, entry.size, False)
        records.append(record)

        def chunks(entry: FileEntry = entry, digest=digest, record: EntryRecord = record):
            yield from read_chunks(collection, entry, digest.update)
            record.sha256 = digest.digest()

        method = ZIP_64 if zip64 else ZIP_32
        yield entry.arcname, entry.mtime, stat.S_IFREG | entry.mode, method, chunks()


def create_exclusive(path: Path) -> int:
    """Create a new file with mode 0600. Never follow or reuse an existing name."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        return os.open(path, flags, 0o600)
    except FileExistsError:
        raise WriteError(f"{path}: already exists; refusing to write through it") from None
    except OSError as exc:
        raise WriteError(f"{path}: {exc.strerror}") from None


def write_part(
    collection: Collection,
    entries: Iterable[tuple[FileEntry, bool]],
    password: Password,
    level: int,
    path: Path,
) -> PartResult:
    """Write `entries` (each paired with its zip64 choice) to a new file at `path`."""
    result = PartResult(path)
    fd = create_exclusive(path)
    try:
        stream = stream_zip(
            _members(collection, entries, result.records),
            chunk_size=OUTPUT_CHUNK,
            get_compressobj=compressor_factory(level),
            extended_timestamps=False,
            password=password.for_stream_zip(),
        )
        for chunk in stream:
            view = memoryview(chunk)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            result.size += len(chunk)
        os.fsync(fd)
    except OSError as exc:
        raise WriteError(f"{path}: {exc.strerror}") from None
    finally:
        os.close(fd)
    return result
