"""Run one archive job: collect → plan → write → verify → publish (SPEC.md §5)."""

import os
import sys
from argparse import Namespace
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import TextIO

from zipseal import plan
from zipseal.collect import DOS_MAX, DOS_MIN, Collection, FileEntry
from zipseal.errors import InputError, VerifyError, WriteError
from zipseal.output import Output
from zipseal.passwords import Password
from zipseal.plan import Layout, PartBudget
from zipseal.verify import verify_part
from zipseal.write import Extra, PartResult, write_part

MANIFEST_NAME = "MANIFEST.txt"


def _worst_inner(entries: list[FileEntry]) -> int:
    """Bound on a single inner zip holding every entry (for the no-cap case)."""
    total = plan.END_RECORDS
    for e in entries:
        total += plan.local_bound(e, True, False) + plan.central_size(e, True, False)
    return total


class _Manifest:
    """MANIFEST.txt (SPEC.md §4, §6.8). Part numbers are zero-padded to the digit count
    of the number of entries, so the size is known before parts are assigned."""

    def __init__(self, entries: list[FileEntry]) -> None:
        if any(e.arcname.casefold() == MANIFEST_NAME.casefold() for e in entries):
            raise InputError(f"an input is already named {MANIFEST_NAME} at the archive root")
        self.entries = entries
        self.width = len(str(max(len(entries), 1)))
        size = len(self.render([0] * len(entries), 0))
        now = min(max(datetime.now().replace(microsecond=0), DOS_MIN), DOS_MAX)
        self.entry = FileEntry(-1, (), MANIFEST_NAME, size, now, 0o644, False, ())

    def render(self, part_of: list[int], parts: int) -> bytes:
        w = self.width
        lines = [f"zipseal manifest: {len(self.entries)} entries in {parts:0{w}d} parts\n"]
        lines += [f"{n:0{w}d}\t{e.arcname}\n" for n, e in zip(part_of, self.entries, strict=True)]
        return "".join(lines).encode("utf-8")

    def reserve(self, encrypted: bool) -> int:
        return plan.local_bound(self.entry, True, encrypted) + plan.central_size(
            self.entry, True, encrypted
        )


def make_layout(args: Namespace, entries: list[FileEntry], manifest: _Manifest | None) -> Layout:
    layout = Layout(args.max_size, hide_names=args.hide_names)
    if manifest is not None:
        layout.reserve = manifest.reserve(layout.encrypted)
    if args.hide_names:
        layout.outer64 = plan.outer_zip64(args.max_size, _worst_inner(entries))
    return layout


def check_fits(entries: list[FileEntry], layout: Layout) -> None:
    """Stop before writing if any single entry cannot fit in an empty part (§6.4)."""
    if layout.max_size is None:
        return
    if layout.reserve and not layout.fits(layout.reserve + plan.END_RECORDS):
        raise InputError(f"{MANIFEST_NAME} alone does not fit in a {layout.max_size:,}-byte part")
    too_big = [e for e in entries if not plan.fits_alone(e, layout)]
    if too_big:
        listing = "\n".join(f"  {e.arcname} ({e.size:,} bytes)" for e in too_big[:20])
        more = f"\n  ... and {len(too_big) - 20} more" if len(too_big) > 20 else ""
        raise InputError(
            f"these entries cannot fit in a {layout.max_size:,}-byte part:\n{listing}{more}\n"
            "Raise --max-size, or split them with 7-Zip spanned volumes, for example:\n"
            "  7zz a -tzip -mem=AES256 -p -v25m big.zip FILE"
        )


def estimate_parts(args: Namespace, entries: list[FileEntry]) -> int:
    """The "at most N parts" figure for --dry-run."""
    manifest = _Manifest(entries) if args.manifest else None
    layout = make_layout(args, entries, manifest)
    check_fits(entries, layout)
    if layout.max_size is None:
        return 1
    return len(plan.assign_upfront(entries, layout, args.order))


def write_archive(
    args: Namespace,
    collection: Collection,
    get_password: Callable[[Namespace], Password],
    err: TextIO | None = None,
) -> list[PartResult]:
    log: TextIO = err or sys.stderr
    entries = collection.entries
    out = Output(args.output, force=args.force, warn=log)
    out.preflight()
    manifest = _Manifest(entries) if args.manifest else None
    layout = make_layout(args, entries, manifest)
    check_fits(entries, layout)

    # Upfront assignment for --order size and --manifest (§6.3); else stream.
    groups: list[list[FileEntry]] | None = None
    extras: list[Extra] = []
    if layout.max_size is not None and (args.order == "size" or manifest is not None):
        groups = plan.assign_upfront(entries, layout, args.order)
    if manifest is not None:
        if groups is None:
            groups = [list(entries)]
        part_of_arc = {e.arcname: i for i, g in enumerate(groups, 1) for e in g}
        data = manifest.render([part_of_arc[e.arcname] for e in entries], len(groups))
        extras = [Extra(manifest.entry, data)]

    password = get_password(args)
    try:
        results: list[PartResult] = []

        progress = log.isatty()

        def one_part(queue: deque[FileEntry]) -> None:
            path = out.new_partial(len(results) + 1)
            if progress:
                print(f"zipseal: writing part {len(results) + 1} ...", file=log, flush=True)
            budget = PartBudget(layout)
            results.append(
                write_part(collection, queue, budget, password, args.level, path, extras)
            )

        if groups is not None:
            for group in groups:
                queue = deque(group)
                one_part(queue)
                if queue:
                    raise WriteError("internal error: a planned part did not fit")
        else:
            queue = deque(entries)
            one_part(queue)
            while queue:
                one_part(queue)

        if progress and not args.no_verify:
            print(f"zipseal: verifying {len(results)} part(s) ...", file=log, flush=True)
        for r in results:
            size = os.stat(r.path).st_size
            if args.max_size is not None and size > args.max_size:
                raise VerifyError(f"{r.path.name}: {size:,} bytes exceeds --max-size")
            if not args.no_verify:
                inner = (r.inner_size, r.inner_tail) if args.hide_names else None
                verify_part(r.path, password, r.records, inner=inner)
        finals = out.final_names(len(results))
        if password.generated:
            print(f"zipseal: generated password: {password.value}", file=log)
        out.publish([r.path for r in results], finals)
        for r, final in zip(results, finals, strict=True):
            r.path = final
        return results
    finally:
        out.cleanup()
