"""Stream entries into one part (SPEC.md §6.2, §6.5, §6.7).

Methods are always explicit (never ZIP_AUTO), so the caller's compressor is used
and the bounds in plan.py apply. A counting wrapper around the compressor gives
the exact size of every member as it finishes, which the admission rule needs.

With --hide-names, the members go into an unencrypted inner zip, and that zip's
bytes stream straight into one AES-encrypted outer entry. No plaintext touches disk.
"""

import hashlib
import os
import stat
import zlib
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from stream_zip import NO_COMPRESSION_32, NO_COMPRESSION_64, ZIP_32, ZIP_64, stream_zip

from zipseal import plan
from zipseal.collect import DOS_MIN, Collection, FileEntry
from zipseal.errors import WriteError
from zipseal.passwords import Password
from zipseal.plan import PartBudget
from zipseal.sources import read_chunks

OUTPUT_CHUNK = 1 << 16
Member = tuple[Any, ...]


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
    inner_size: int = 0  # --hide-names: size of the inner zip
    inner_tail: int = 0  # --hide-names: bytes of central directory + end records


@dataclass(frozen=True)
class Extra:
    """A generated member, such as MANIFEST.txt, appended to every part."""

    entry: FileEntry
    data: bytes


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

    def factory(self) -> "zlib._Compress":
        return cast("zlib._Compress", _CountingCompressor(self._make(), self))


class _Members:
    """Yield members while the next one fits the budget; stop to end the part.

    stream-zip finishes a member before pulling the next one, so each pull is the
    moment to add the previous member's exact local size to the budget.
    """

    def __init__(
        self,
        collection: Collection,
        queue: deque[FileEntry],
        budget: PartBudget,
        counter: _Counter,
        extras: list[Extra],
    ) -> None:
        self.collection = collection
        self.queue = queue
        self.budget = budget
        self.counter = counter
        self.extras = extras
        self.records: list[EntryRecord] = []
        self.zip64_used = False
        self._pending: tuple[FileEntry, bool] | None = None

    def _settle(self) -> None:
        if self._pending is None:
            return
        entry, zip64 = self._pending
        enc = self.budget.layout.encrypted
        data = 0 if entry.is_dir else self.counter.bytes
        self.budget.written_local += (
            plan.local_header(entry, zip64, enc)
            + plan.overhead(enc)
            + data
            + plan.descriptor(entry, zip64)
        )
        self._pending = None

    def _member(self, entry: FileEntry, zip64: bool, payload: bytes | None) -> Member:
        self._pending = (entry, zip64)
        self.zip64_used = self.zip64_used or zip64
        self.counter.bytes = 0
        if entry.is_dir:
            method = NO_COMPRESSION_64(0, 0) if zip64 else NO_COMPRESSION_32(0, 0)
            self.records.append(EntryRecord(entry.arcname, 0, True, hashlib.sha256().digest()))
            return entry.arcname, entry.mtime, stat.S_IFDIR | entry.mode, method, ()
        digest = hashlib.sha256()
        record = EntryRecord(entry.arcname, entry.size, False)
        self.records.append(record)
        if payload is not None:
            digest.update(payload)
            record.sha256 = digest.digest()
            chunks: Iterable[bytes] = (payload,)
        else:
            chunks = self._read(entry, digest, record)
        method = ZIP_64 if zip64 else ZIP_32
        return entry.arcname, entry.mtime, stat.S_IFREG | entry.mode, method, chunks

    def _read(self, entry: FileEntry, digest: Any, record: EntryRecord) -> Iterator[bytes]:
        yield from read_chunks(self.collection, entry, digest.update)
        record.sha256 = digest.digest()

    def __iter__(self) -> Iterator[Member]:
        while True:
            self._settle()
            if not self.queue:
                break
            entry = self.queue[0]
            c = self.budget.try_admit(entry)
            if c is None:
                if self.budget.index == 0:
                    raise WriteError(f"{entry.arcname}: does not fit in an empty part")
                break
            self.queue.popleft()
            yield self._member(entry, c.zip64, None)
        for extra in self.extras:
            # Reserved in the layout, so it is costed but not admitted.
            b = self.budget
            enc = b.layout.encrypted
            c = plan.cost(
                extra.entry,
                index=b.index,
                offset=b.written_local,
                central_so_far=b.central,
                encrypted=enc,
            )
            b.index += 1
            b.central += c.central
            yield self._member(extra.entry, c.zip64, extra.data)
            self._settle()


def create_exclusive(path: Path) -> int:
    """Create a new file with mode 0600. Never follow or reuse an existing name."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        return os.open(path, flags, 0o600)
    except FileExistsError:
        raise WriteError(f"{path}: already exists; refusing to write through it") from None
    except OSError as exc:
        raise WriteError(f"{path}: {exc.strerror}") from None


class _Tee:
    """Count the inner zip's bytes on their way into the outer entry."""

    def __init__(self, source: Iterable[bytes]) -> None:
        self.source = source
        self.size = 0

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self.source:
            self.size += len(chunk)
            yield chunk


def write_part(
    collection: Collection,
    queue: deque[FileEntry],
    budget: PartBudget,
    password: Password,
    level: int,
    path: Path,
    extras: list[Extra] | None = None,
) -> PartResult:
    """Write entries from the front of `queue` to a new file at `path` until one does
    not fit `budget`. Admitted entries are removed from the queue. `extras` are
    appended to the part; their size must already be reserved in the layout.
    """
    layout = budget.layout
    result = PartResult(path)
    counter = _Counter(level)
    members = _Members(collection, queue, budget, counter, extras or [])
    inner = stream_zip(
        members,
        chunk_size=OUTPUT_CHUNK,
        get_compressobj=counter.factory,
        extended_timestamps=False,
        password=None if layout.hide_names else password.for_stream_zip(),
    )
    tee: _Tee | None = None
    outer_counter: _Counter | None = None
    if layout.hide_names:
        tee = _Tee(inner)
        outer_counter = _Counter(0)
        method = ZIP_64 if layout.outer64 else ZIP_32
        stream = stream_zip(
            [(plan.OUTER_NAME, DOS_MIN, stat.S_IFREG | 0o600, method, tee)],
            chunk_size=OUTPUT_CHUNK,
            get_compressobj=outer_counter.factory,
            extended_timestamps=False,
            password=password.for_stream_zip(),
        )
    else:
        stream = inner

    fd = create_exclusive(path)
    try:
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

    result.records = members.records
    end = plan.END_RECORDS if members.zip64_used else plan.EOCD_ONLY
    inner_predicted = budget.written_local + budget.central + end
    if tee is not None and outer_counter is not None:
        result.inner_size = tee.size
        result.inner_tail = budget.central + end
        _check_accounting(path, inner_predicted, tee.size, "inner zip")
        outer_predicted = plan.outer_exact(layout.outer64, outer_counter.bytes)
        _check_accounting(path, outer_predicted, result.size, "outer zip")
    else:
        _check_accounting(path, inner_predicted, result.size, "part")
    if layout.max_size is not None and result.size > layout.max_size:
        raise WriteError(f"{path.name}: {result.size} bytes exceeds the cap")  # pragma: no cover
    return result


def _check_accounting(path: Path, predicted: int, actual: int, what: str) -> None:
    # The admission rule is only sound if this accounting is exact.
    if predicted != actual:
        raise WriteError(
            f"{path.name}: internal size accounting for the {what} is off by "
            f"{actual - predicted} bytes; the installed stream-zip may have changed"
        )
