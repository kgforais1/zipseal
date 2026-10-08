"""Size bounds and method choice (SPEC.md §6.2).

The framing sizes below match what stream-zip 0.0.84 writes with a password and
extended timestamps off. tests/test_plan.py measures real archives and fails if
the library ever writes something different.
"""

from dataclasses import dataclass

from zipseal.collect import FileEntry

ZIP32_LIMIT = 0xFFFFFFFF
ZIP64_FROM_INDEX = 65_534  # 0-based: the 65,535th entry onward uses a 64-bit method

LOCAL_FIXED = 30
CENTRAL_FIXED = 46
AES_EXTRA = 11  # header 4 + vendor version, vendor id, strength, method
ZIP64_LOCAL_EXTRA = 20  # header 4 + uncompressed 8 + compressed 8
ZIP64_CENTRAL_EXTRA = 28  # header 4 + uncompressed 8 + compressed 8 + offset 8
AES_OVERHEAD = 28  # salt 16 + password verifier 2 + HMAC 10
DESCRIPTOR_32 = 16  # signature, CRC, compressed 4, uncompressed 4
DESCRIPTOR_64 = 24  # signature, CRC, compressed 8, uncompressed 8
END_RECORDS = 98  # Zip64 end record 56 + locator 20 + EOCD 22, always reserved
EOCD_ONLY = 22  # what is actually written when no member is 64-bit


def deflate_bound(n: int) -> int:
    """zlib's bound for raw deflate with memLevel=8, valid at every level 0-9."""
    return n + (n >> 12) + (n >> 14) + (n >> 25) + 7


@dataclass(frozen=True)
class Cost:
    zip64: bool
    local: int  # upper bound on the bytes written while the entry streams
    central: int  # exact size of its central directory entry


def name_len(entry: FileEntry) -> int:
    return len(entry.arcname.encode("utf-8"))


def local_header(entry: FileEntry, zip64: bool) -> int:
    return LOCAL_FIXED + name_len(entry) + AES_EXTRA + (ZIP64_LOCAL_EXTRA if zip64 else 0)


def descriptor(entry: FileEntry, zip64: bool) -> int:
    if entry.is_dir:
        return 0  # stream-zip writes no data descriptor for empty stored entries
    return DESCRIPTOR_64 if zip64 else DESCRIPTOR_32


def local_bound(entry: FileEntry, zip64: bool) -> int:
    data = 0 if entry.is_dir else deflate_bound(entry.size)
    return local_header(entry, zip64) + AES_OVERHEAD + data + descriptor(entry, zip64)


def central_size(entry: FileEntry, zip64: bool) -> int:
    return CENTRAL_FIXED + name_len(entry) + AES_EXTRA + (ZIP64_CENTRAL_EXTRA if zip64 else 0)


def cost(entry: FileEntry, *, index: int, offset: int, central_so_far: int) -> Cost:
    """Choose ZIP_32 or ZIP_64 for the entry at `index` in its part, and bound its size.

    `offset` is an upper bound on the bytes already written to the part, and
    `central_so_far` the size of the central entries already reserved.
    """
    small = local_bound(entry, False)
    zip64 = (
        index >= ZIP64_FROM_INDEX
        or offset + small > ZIP32_LIMIT
        or central_so_far + central_size(entry, False) > ZIP32_LIMIT
    )
    return Cost(zip64, local_bound(entry, zip64), central_size(entry, zip64))


@dataclass
class PartBudget:
    """Running totals for the part being written, used by the admission rule (§6.2)."""

    max_size: int | None
    reserve: int = 0  # fixed extra bytes per part (manifest, outer layer); added later
    index: int = 0
    written_local: int = 0  # exact bytes of the members already finished
    central: int = 0  # central entries reserved so far

    def try_admit(self, entry: FileEntry) -> Cost | None:
        c = cost(entry, index=self.index, offset=self.written_local, central_so_far=self.central)
        if self.max_size is not None:
            total = self.written_local + c.local + self.central + c.central + END_RECORDS
            if total + self.reserve > self.max_size:
                return None
        self.index += 1
        self.central += c.central
        return c


def fits_alone(entry: FileEntry, max_size: int, reserve: int = 0) -> bool:
    c = cost(entry, index=0, offset=0, central_so_far=0)
    return c.local + c.central + END_RECORDS + reserve <= max_size


def bound_parts(entries: list[FileEntry], max_size: int | None, reserve: int = 0) -> int:
    """Upper bound on the part count for --order path, from worst-case sizes."""
    if not entries:
        return 1
    parts = 1
    budget = PartBudget(max_size, reserve)
    for entry in entries:
        c = budget.try_admit(entry)
        if c is None:
            parts += 1
            budget = PartBudget(max_size, reserve)
            c = budget.try_admit(entry)
            if c is None:
                raise RuntimeError("fits_alone() must be checked first")
        budget.written_local += c.local
    return parts


def first_fit_decreasing(
    entries: list[FileEntry], max_size: int, reserve: int = 0
) -> list[list[FileEntry]]:
    """Assign entries to parts from bounds alone (--order size, §6.3). Never re-split."""
    order = sorted(
        entries, key=lambda e: (-(local_bound(e, False) + central_size(e, False)), e.arcname)
    )
    budgets: list[PartBudget] = []
    parts: list[list[FileEntry]] = []
    for entry in order:
        for budget, members in zip(budgets, parts, strict=True):
            c = budget.try_admit(entry)
            if c is not None:
                budget.written_local += c.local
                members.append(entry)
                break
        else:
            budget = PartBudget(max_size, reserve)
            c = budget.try_admit(entry)
            if c is None:
                raise RuntimeError("fits_alone() must be checked first")
            budget.written_local += c.local
            budgets.append(budget)
            parts.append([entry])
    return parts
