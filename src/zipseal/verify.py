"""Re-read each written part and prove it is intact (SPEC.md §6.6, §6.7)."""

import hashlib
import os
from collections import deque
from collections.abc import Iterable, Iterator
from pathlib import Path

from stream_unzip import AE_2, AES_256, NO_ENCRYPTION, UnzipError, stream_unzip

from zipseal import plan, zipcheck
from zipseal.errors import VerifyError
from zipseal.passwords import Password
from zipseal.write import EntryRecord

READ_CHUNK = 1 << 16


def _file_chunks(fd: int) -> Iterator[bytes]:
    os.lseek(fd, 0, os.SEEK_SET)
    while chunk := os.read(fd, READ_CHUNK):
        yield chunk


def _check_entries(
    label: str,
    members: Iterable[tuple[bytes, int | None, Iterable[bytes]]],
    records: list[EntryRecord],
) -> None:
    expected = iter(records)
    for raw_name, _, chunks in members:
        digest = hashlib.sha256()
        for chunk in chunks:
            digest.update(chunk)
        record = next(expected, None)
        name = raw_name.decode("utf-8", "replace")
        if record is None or name != record.arcname:
            raise VerifyError(f"{label}: unexpected entry {name!r}")
        if digest.digest() != record.sha256:
            raise VerifyError(f"{label}: {name} does not match its source")
    if next(expected, None) is not None:
        raise VerifyError(f"{label}: entries are missing")


class _TailKeeper:
    """Pass the inner zip through, counting it and keeping its last `keep` bytes."""

    def __init__(self, source: Iterable[bytes], keep: int) -> None:
        self.source = iter(source)
        self.keep = keep
        self.size = 0
        self._tail: deque[bytes] = deque()
        self._tail_len = 0

    def __iter__(self) -> Iterator[bytes]:
        return self

    def __next__(self) -> bytes:
        chunk = next(self.source)
        self.size += len(chunk)
        self._tail.append(chunk)
        self._tail_len += len(chunk)
        while self._tail and self._tail_len - len(self._tail[0]) >= self.keep:
            self._tail_len -= len(self._tail.popleft())
        return chunk

    def tail(self) -> bytes:
        data = b"".join(self._tail)
        return data[len(data) - min(self.keep, len(data)) :]


def verify_part(
    path: Path,
    password: Password,
    records: list[EntryRecord],
    inner: tuple[int, int] | None = None,
) -> None:
    """Decrypt every entry (checking each HMAC), compare SHA-256 values, check structure.

    `inner` is (inner zip size, central directory + end record bytes) under
    --hide-names, where the part holds one encrypted payload.zip.
    """
    label = path.name
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise VerifyError(f"{label}: cannot reopen for verification: {exc.strerror}") from None
    try:
        outer = stream_unzip(
            _file_chunks(fd),
            password=password.encode(),
            allowed_encryption_mechanisms=(AE_2, AES_256),
        )
        try:
            if inner is None:
                _check_entries(label, outer, records)
            else:
                _verify_inner(label, outer, records, inner)
        except UnzipError as exc:
            raise VerifyError(f"{label}: failed to decrypt ({type(exc).__name__})") from None
        if inner is None:
            zipcheck.check_file(fd, [(r.arcname, r.size) for r in records], label)
        else:
            zipcheck.check_file(fd, [(plan.OUTER_NAME, inner[0])], label)
    finally:
        os.close(fd)


def _verify_inner(
    label: str,
    outer: Iterable[tuple[bytes, int | None, Iterable[bytes]]],
    records: list[EntryRecord],
    inner: tuple[int, int],
) -> None:
    inner_size, inner_tail = inner
    members = iter(outer)
    first = next(members, None)
    if first is None or first[0] != plan.OUTER_NAME.encode():
        raise VerifyError(f"{label}: does not hold {plan.OUTER_NAME}")
    payload = _TailKeeper(first[2], inner_tail)
    inner_label = f"{label}/{plan.OUTER_NAME}"
    _check_entries(
        inner_label,
        stream_unzip(payload, allowed_encryption_mechanisms=(NO_ENCRYPTION,)),
        records,
    )
    for _ in payload:  # drain the inner central directory, so the outer HMAC is checked
        pass
    if next(members, None) is not None:
        raise VerifyError(f"{label}: holds more than {plan.OUTER_NAME}")
    if payload.size != inner_size:
        raise VerifyError(f"{inner_label}: size differs from what was written")
    zipcheck.check_inner_tail(payload.tail(), inner_size, records, inner_label)
