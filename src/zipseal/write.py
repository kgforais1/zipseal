"""Stream entries into one encrypted part (SPEC.md §6.2, §6.5).

Methods are always explicit (never ZIP_AUTO), so the caller's compressor is used
and the bounds in plan.py apply.
"""

import hashlib
import os
import stat
import zlib
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from stream_zip import NO_COMPRESSION_32, NO_COMPRESSION_64, ZIP_32, ZIP_64, stream_zip

from zipseal import plan
from zipseal.collect import Collection, FileEntry
from zipseal.errors import WriteError
from zipseal.passwords import Password
from zipseal.plan import PartBudget
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


class _CountingCompressor:
    """Wraps a compressobj and counts the bytes it emits (design A, plan Phase 4)."""

    def __init__(self, inner: "zlib._Compress", counter: "_Counter") -> None:
        self._inner = inner
        self._counter = counter

    def compress(self, data: bytes) -> bytes:
        out = self._inner.compress(data)
        self._counter.bytes += len(out)
        return out

    def flush(self, *args: int) -> bytes:
        out = self._inner.flush(*args)
        self._counter.bytes += len(out)
        return out


class _Counter:
    def __init__(self, level: int) -> None:
        self.bytes = 0
        self._make = compressor_factory(level)

    def factory(self) -> "_CountingCompressor":
        return _CountingCompressor(self._make(), self)


def _members(
    collection: Collection,
    queue: deque[FileEntry],
    budget: PartBudget,
    counter: _Counter,
    records: list[EntryRecord],
    zip64_used: list[bool],
) -> Iterator[tuple]:
    """Yield members while the next one fits the budget; stop to end the part.

    stream-zip finishes a member before pulling the next one, so each pull is the
    moment to add the previous member's exact local size to the budget.
    """
    pending: tuple[FileEntry, bool] | None = None
    while True:
        if pending is not None:
            entry, zip64 = pending
            data = 0 if entry.is_dir else counter.bytes
            budget.written_local += (
                plan.local_header(entry, zip64)
                + plan.AES_OVERHEAD
                + data
                + plan.descriptor(entry, zip64)
            )
            pending = None
        if not queue:
            return
        entry = queue[0]
        c = budget.try_admit(entry)
        if c is None:
            if budget.index == 0:
                raise WriteError(f"{entry.arcname}: does not fit in an empty part")
            return
        queue.popleft()
        pending = (entry, c.zip64)
        zip64_used[0] = zip64_used[0] or c.zip64
        counter.bytes = 0
        if entry.is_dir:
            method = NO_COMPRESSION_64(0, 0) if c.zip64 else NO_COMPRESSION_32(0, 0)
            records.append(EntryRecord(entry.arcname, 0, True, hashlib.sha256().digest()))
            yield entry.arcname, entry.mtime, stat.S_IFDIR | entry.mode, method, ()
            continue
        digest = hashlib.sha256()
        record = EntryRecord(entry.arcname, entry.size, False)
        records.append(record)

        def chunks(entry: FileEntry = entry, digest=digest, record: EntryRecord = record):
            yield from read_chunks(collection, entry, digest.update)
            record.sha256 = digest.digest()

        method = ZIP_64 if c.zip64 else ZIP_32
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
    queue: deque[FileEntry],
    budget: PartBudget,
    password: Password,
    level: int,
    path: Path,
) -> PartResult:
    """Write entries from the front of `queue` to a new file at `path` until one does
    not fit `budget`. Admitted entries are removed from the queue.
    """
    result = PartResult(path)
    counter = _Counter(level)
    zip64_used = [False]
    fd = create_exclusive(path)
    try:
        stream = stream_zip(
            _members(collection, queue, budget, counter, result.records, zip64_used),
            chunk_size=OUTPUT_CHUNK,
            get_compressobj=cast("Callable[[], zlib._Compress]", counter.factory),
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
    end = plan.END_RECORDS if zip64_used[0] else plan.EOCD_ONLY
    predicted = budget.written_local + budget.central + end
    if predicted != result.size:
        # The admission rule is only sound if this accounting is exact.
        raise WriteError(
            f"{path.name}: internal size accounting is off by {result.size - predicted} "
            "bytes; the installed stream-zip may have changed"
        )
    if budget.max_size is not None and result.size > budget.max_size:
        raise WriteError(f"{path.name}: {result.size} bytes exceeds the cap")  # pragma: no cover
    return result
