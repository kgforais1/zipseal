"""Re-read each written part and prove it is intact (SPEC.md §6.6)."""

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

from stream_unzip import AE_2, AES_256, UnzipError, stream_unzip

from zipseal import zipcheck
from zipseal.errors import VerifyError
from zipseal.passwords import Password
from zipseal.write import EntryRecord

READ_CHUNK = 1 << 16


def _file_chunks(fd: int) -> Iterator[bytes]:
    os.lseek(fd, 0, os.SEEK_SET)
    while chunk := os.read(fd, READ_CHUNK):
        yield chunk


def verify_part(path: Path, password: Password, records: list[EntryRecord]) -> None:
    """Decrypt every entry (checking each HMAC), compare SHA-256 values, check structure."""
    label = path.name
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise VerifyError(f"{label}: cannot reopen for verification: {exc.strerror}") from None
    try:
        expected = iter(records)
        try:
            for raw_name, _, chunks in stream_unzip(
                _file_chunks(fd),
                password=password.encode(),
                allowed_encryption_mechanisms=(AE_2, AES_256),
            ):
                digest = hashlib.sha256()
                for chunk in chunks:
                    digest.update(chunk)
                record = next(expected, None)
                name = raw_name.decode("utf-8", "replace")
                if record is None or name != record.arcname:
                    raise VerifyError(f"{label}: unexpected entry {name!r}")
                if digest.digest() != record.sha256:
                    raise VerifyError(f"{label}: {name} does not match its source")
        except UnzipError as exc:
            raise VerifyError(f"{label}: failed to decrypt ({type(exc).__name__})") from None
        if next(expected, None) is not None:
            raise VerifyError(f"{label}: entries are missing")
        zipcheck.check_file(fd, [(r.arcname, r.size) for r in records], label)
    finally:
        os.close(fd)
