"""Open and read collected sources safely (SPEC.md §6.5).

Each source is reached from the root descriptor held since collection, one
component at a time. Every component's (device, inode) must match what
collection recorded, so a file or folder swapped in the meantime is refused.
"""

import os
import stat
from collections.abc import Callable, Iterator

from zipseal.collect import Collection, FileEntry
from zipseal.errors import WriteError

CHUNK = 1 << 16


def _changed(entry: FileEntry, what: str) -> WriteError:
    return WriteError(
        f"{entry.arcname}: {what} changed since it was collected; nothing was written"
    )


def open_source(collection: Collection, entry: FileEntry) -> int:
    """Return a read-only descriptor for a regular-file entry, after identity checks."""
    nofollow = 0 if collection.follow_symlinks else os.O_NOFOLLOW
    fd = collection.roots[entry.root]
    owned: list[int] = []
    try:
        last = len(entry.relparts) - 1
        for i, (part, ident) in enumerate(zip(entry.relparts, entry.chain, strict=True)):
            if i < last:
                flags = os.O_RDONLY | os.O_DIRECTORY | nofollow
            else:
                flags = os.O_RDONLY | os.O_NONBLOCK | nofollow
            try:
                fd = os.open(part, flags, dir_fd=fd)
            except OSError:
                raise _changed(entry, "the file or a folder above it") from None
            owned.append(fd)
            st = os.fstat(fd)
            if (st.st_dev, st.st_ino) != ident:
                raise _changed(entry, "the file" if i == last else "a folder above it")
            if i == last and not stat.S_ISREG(st.st_mode):
                raise _changed(entry, "the file type")
        os.set_blocking(fd, True)
        for other in owned[:-1]:
            os.close(other)
        return owned[-1]
    except BaseException:
        for other in owned:
            os.close(other)
        raise


def read_chunks(
    collection: Collection, entry: FileEntry, update: Callable[[bytes], None]
) -> Iterator[bytes]:
    """Open the entry lazily and yield its bytes, passing each chunk to `update`.

    Fails if the size differs from collection. Reads at most size + 1 bytes, so a
    growing file cannot run on.
    """
    fd = open_source(collection, entry)
    remaining = entry.size + 1
    total = 0
    try:
        while remaining > 0:
            try:
                chunk = os.read(fd, min(CHUNK, remaining))
            except OSError as exc:
                raise WriteError(f"{entry.arcname}: cannot read: {exc.strerror}") from None
            if not chunk:
                break
            remaining -= len(chunk)
            total += len(chunk)
            if total > entry.size:
                raise _changed(entry, "the file size")
            update(chunk)
            yield chunk
        if total != entry.size:
            raise _changed(entry, "the file size")
    finally:
        os.close(fd)
