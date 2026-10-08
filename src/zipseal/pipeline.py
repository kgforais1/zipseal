"""Run one archive job: collect → write → verify → publish (SPEC.md §5)."""

import sys
from argparse import Namespace
from collections.abc import Callable
from typing import TextIO

from zipseal import plan
from zipseal.collect import Collection, FileEntry
from zipseal.errors import UsageError
from zipseal.output import Output
from zipseal.passwords import Password
from zipseal.verify import verify_part
from zipseal.write import PartResult, write_part


def choose_methods(entries: list[FileEntry]) -> list[tuple[FileEntry, bool]]:
    """Pair each entry with its zip64 choice for a single, uncapped part."""
    offset = 0
    central = 0
    chosen = []
    for index, entry in enumerate(entries):
        c = plan.cost(entry, index=index, offset=offset, central_so_far=central)
        offset += c.local
        central += c.central
        chosen.append((entry, c.zip64))
    return chosen


def write_archive(
    args: Namespace,
    collection: Collection,
    get_password: Callable[[Namespace], Password],
    err: TextIO | None = None,
) -> list[PartResult]:
    err = err or sys.stderr
    if args.max_size is not None:
        raise UsageError("--max-size is not implemented yet")
    out = Output(args.output, force=args.force, warn=err)
    out.preflight()
    password = get_password(args)
    try:
        partial = out.new_partial(1)
        result = write_part(
            collection, choose_methods(collection.entries), password, args.level, partial
        )
        results = [result]
        if not args.no_verify:
            for r in results:
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
