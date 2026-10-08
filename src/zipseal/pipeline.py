"""Run one archive job: collect → write → verify → publish (SPEC.md §5)."""

import os
import sys
from argparse import Namespace
from collections import deque
from collections.abc import Callable
from typing import TextIO

from zipseal import plan
from zipseal.collect import Collection, FileEntry
from zipseal.errors import InputError, VerifyError, WriteError
from zipseal.output import Output
from zipseal.passwords import Password
from zipseal.plan import PartBudget
from zipseal.verify import verify_part
from zipseal.write import PartResult, write_part


def check_fits(entries: list[FileEntry], max_size: int | None) -> None:
    """Stop before writing if any single entry cannot fit in an empty part (§6.4)."""
    if max_size is None:
        return
    too_big = [e for e in entries if not plan.fits_alone(e, max_size)]
    if too_big:
        listing = "\n".join(f"  {e.arcname} ({e.size:,} bytes)" for e in too_big[:20])
        more = f"\n  ... and {len(too_big) - 20} more" if len(too_big) > 20 else ""
        raise InputError(
            f"these entries cannot fit in a {max_size:,}-byte part:\n{listing}{more}\n"
            "Raise --max-size, or split them with 7-Zip spanned volumes, for example:\n"
            "  7zz a -tzip -mem=AES256 -p -v25m big.zip FILE"
        )


def plan_groups(args: Namespace, entries: list[FileEntry]) -> list[list[FileEntry]] | None:
    """Upfront assignment for --order size (§6.3); None means stream in path order."""
    if args.max_size is not None and args.order == "size":
        return plan.first_fit_decreasing(entries, args.max_size)
    return None


def write_archive(
    args: Namespace,
    collection: Collection,
    get_password: Callable[[Namespace], Password],
    err: TextIO | None = None,
) -> list[PartResult]:
    err = err or sys.stderr
    out = Output(args.output, force=args.force, warn=err)
    out.preflight()
    check_fits(collection.entries, args.max_size)
    groups = plan_groups(args, collection.entries)
    password = get_password(args)
    try:
        results: list[PartResult] = []
        if groups is not None:
            for group in groups:
                queue = deque(group)
                budget = PartBudget(args.max_size)
                path = out.new_partial(len(results) + 1)
                results.append(write_part(collection, queue, budget, password, args.level, path))
                if queue:
                    raise WriteError("internal error: a planned part did not fit")
        else:
            queue = deque(collection.entries)
            while True:
                budget = PartBudget(args.max_size)
                path = out.new_partial(len(results) + 1)
                results.append(write_part(collection, queue, budget, password, args.level, path))
                if not queue:
                    break
        for r in results:
            size = os.stat(r.path).st_size
            if args.max_size is not None and size > args.max_size:
                raise VerifyError(f"{r.path.name}: {size:,} bytes exceeds --max-size")
            if not args.no_verify:
                verify_part(r.path, password, r.records)
        finals = out.final_names(len(results))
        if password.generated:
            print(f"zipseal: generated password: {password.value}", file=err)
        out.publish([r.path for r in results], finals)
        for r, final in zip(results, finals, strict=True):
            r.path = final
        return results
    finally:
        out.cleanup()
