"""Size bounds, method choice and part admission (SPEC.md §6.2, §6.3, §6.7).

The framing sizes below match what stream-zip 0.0.84 writes with extended
timestamps off, with or without a password. tests/test_plan.py measures real
archives, and write.py checks every part's predicted size against the bytes
written, so a library change is caught rather than trusted.
"""

from dataclasses import dataclass, field

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

OUTER_NAME = "payload.zip"


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


def _header(n_len: int, zip64: bool, encrypted: bool) -> int:
    aes = AES_EXTRA if encrypted else 0
    return LOCAL_FIXED + n_len + aes + (ZIP64_LOCAL_EXTRA if zip64 else 0)


def _central(n_len: int, zip64: bool, encrypted: bool) -> int:
    aes = AES_EXTRA if encrypted else 0
    return CENTRAL_FIXED + n_len + aes + (ZIP64_CENTRAL_EXTRA if zip64 else 0)


def local_header(entry: FileEntry, zip64: bool, encrypted: bool = True) -> int:
    return _header(name_len(entry), zip64, encrypted)


def overhead(encrypted: bool) -> int:
    return AES_OVERHEAD if encrypted else 0


def descriptor(entry: FileEntry, zip64: bool) -> int:
    if entry.is_dir:
        return 0  # stream-zip writes no data descriptor for empty stored entries
    return DESCRIPTOR_64 if zip64 else DESCRIPTOR_32


def local_bound(entry: FileEntry, zip64: bool, encrypted: bool = True) -> int:
    data = 0 if entry.is_dir else deflate_bound(entry.size)
    header = local_header(entry, zip64, encrypted)
    return header + overhead(encrypted) + data + descriptor(entry, zip64)


def central_size(entry: FileEntry, zip64: bool, encrypted: bool = True) -> int:
    return _central(name_len(entry), zip64, encrypted)


def cost(
    entry: FileEntry, *, index: int, offset: int, central_so_far: int, encrypted: bool = True
) -> Cost:
    """Choose ZIP_32 or ZIP_64 for the entry at `index` in its part, and bound its size.

    `offset` is an upper bound on the bytes already written to the part, and
    `central_so_far` the size of the central entries already reserved.
    """
    small = local_bound(entry, False, encrypted)
    zip64 = (
        index >= ZIP64_FROM_INDEX
        or offset + small > ZIP32_LIMIT
        or central_so_far + central_size(entry, False, encrypted) > ZIP32_LIMIT
    )
    local = local_bound(entry, zip64, encrypted)
    return Cost(zip64, local, central_size(entry, zip64, encrypted))


# ── --hide-names outer layer (§6.7) ──────────────────────────────────────────


def outer_zip64(max_size: int | None, inner_worst: int) -> bool:
    """The outer entry is 64-bit only if the part could pass 4 GiB."""
    limit = inner_worst if max_size is None else max_size
    return deflate_bound(limit) + 1024 > ZIP32_LIMIT


def outer_fixed(zip64: bool) -> int:
    """Everything in an outer part except the deflated inner zip, at its worst."""
    n = len(OUTER_NAME)
    descriptor_size = DESCRIPTOR_64 if zip64 else DESCRIPTOR_32
    return (
        _header(n, zip64, True)
        + AES_OVERHEAD
        + descriptor_size
        + _central(n, zip64, True)
        + END_RECORDS
    )


def outer_exact(zip64: bool, compressed: int) -> int:
    """The exact size of an outer part whose deflated inner zip is `compressed` bytes."""
    n = len(OUTER_NAME)
    descriptor_size = DESCRIPTOR_64 if zip64 else DESCRIPTOR_32
    end = END_RECORDS if zip64 else EOCD_ONLY
    return (
        _header(n, zip64, True)
        + AES_OVERHEAD
        + compressed
        + descriptor_size
        + _central(n, zip64, True)
        + end
    )


@dataclass
class Layout:
    """How parts are framed: AES entries directly, or (`hide_names`) an unencrypted
    inner zip inside one AES entry named payload.zip."""

    max_size: int | None
    hide_names: bool = False
    reserve: int = 0  # bytes reserved inside every (inner) part, such as a manifest
    outer64: bool = False

    @property
    def encrypted(self) -> bool:
        return not self.hide_names

    def fits(self, inner_total: int) -> bool:
        """Does a part whose (inner) zip is at most `inner_total` bytes fit the cap?"""
        if self.max_size is None:
            return True
        if not self.hide_names:
            return inner_total <= self.max_size
        return deflate_bound(inner_total) + outer_fixed(self.outer64) <= self.max_size


@dataclass
class PartBudget:
    """Running totals for the part being written, used by the admission rule (§6.2)."""

    layout: Layout
    index: int = 0
    written_local: int = 0  # exact bytes of the members already finished
    central: int = 0  # central entries reserved so far
    costs: list[Cost] = field(default_factory=list)

    def try_admit(self, entry: FileEntry) -> Cost | None:
        c = cost(
            entry,
            index=self.index,
            offset=self.written_local,
            central_so_far=self.central,
            encrypted=self.layout.encrypted,
        )
        total = self.written_local + c.local + self.central + c.central + END_RECORDS
        if not self.layout.fits(total + self.layout.reserve):
            return None
        self.index += 1
        self.central += c.central
        self.costs.append(c)
        return c


def fits_alone(entry: FileEntry, layout: Layout) -> bool:
    return PartBudget(layout).try_admit(entry) is not None


def _admit_fresh(budget: PartBudget, entry: FileEntry) -> Cost:
    c = budget.try_admit(entry)
    if c is None:
        raise RuntimeError("fits_alone() must be checked first")
    return c


def assign_upfront(entries: list[FileEntry], layout: Layout, order: str) -> list[list[FileEntry]]:
    """Assign entries to parts from bounds alone, never re-split (§6.3).

    `order="size"` is first-fit-decreasing. `order="path"` keeps path order and
    starts a new part when the next entry's bound does not fit. The path result
    is also the "at most N parts" figure for a streamed --order path run.
    """
    if order == "path":
        parts: list[list[FileEntry]] = [[]]
        budget = PartBudget(layout)
        for entry in entries:
            c = budget.try_admit(entry)
            if c is None:
                parts.append([])
                budget = PartBudget(layout)
                c = _admit_fresh(budget, entry)
            budget.written_local += c.local
            parts[-1].append(entry)
        return parts

    enc = layout.encrypted

    def weight(e: FileEntry) -> int:
        return local_bound(e, False, enc) + central_size(e, False, enc)

    budgets: list[PartBudget] = []
    groups: list[list[FileEntry]] = []
    for entry in sorted(entries, key=lambda e: (-weight(e), e.arcname)):
        for budget, members in zip(budgets, groups, strict=True):
            c = budget.try_admit(entry)
            if c is not None:
                budget.written_local += c.local
                members.append(entry)
                break
        else:
            budget = PartBudget(layout)
            budget.written_local += _admit_fresh(budget, entry).local
            budgets.append(budget)
            groups.append([entry])
    return groups or [[]]
