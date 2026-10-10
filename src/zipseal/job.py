"""The shared core: run one archive job from `Options` (SPEC.md §5).

`cli.py` turns argparse into `Options` and points `warn` at stderr; the GUI turns
its widgets into `Options` and points `warn` at its log area. Both call
`run_job`, so neither front end can skip a step: the strength check, the
size-cap check and the verification loop all live here.

`progress` is an optional `Progress` implementation, which the CLI fills with its
TTY progress lines and the GUI will fill with a progress bar. It is called in
order from the thread that runs this function.
"""

import sys
from collections.abc import Callable
from typing import TextIO

from zipseal import passwords
from zipseal.collect import Collection, collect
from zipseal.errors import EXIT_OK, InputError
from zipseal.options import Options
from zipseal.passwords import Password
from zipseal.pipeline import estimate_parts, write_archive
from zipseal.progress import Progress


def print_dry_run(collection: Collection, options: Options, out: TextIO) -> None:
    """List what would be archived, and how many parts it would need."""
    total = 0
    for entry in collection.entries:
        total += entry.size
        print(f"{entry.size:>14,}  {entry.arcname}", file=out)
    count = len(collection.entries)
    print(f"{count:,} entries, {total:,} bytes before compression", file=out)
    if options.max_size is not None:
        parts = estimate_parts(options, collection.entries)
        print(
            f"at most {parts} part{'s' if parts != 1 else ''} of {options.max_size:,} bytes",
            file=out,
        )


def run_job(
    options: Options,
    get_password: Callable[[Options], Password],
    progress: Progress | None = None,
    warn: TextIO | None = None,
    out: TextIO | None = None,
    password_out: TextIO | None = None,
) -> int:
    """Collect, then write and verify one archive, or only plan it with `dry_run`.

    Returns 0, or raises `ZipsealError`: `cli.main` turns it into an exit code
    and the GUI turns it into a dialog. `warn` is where every warning goes,
    including the password strength ones; `out` is where the dry-run plan goes.

    `password_out` is where the generated password is printed once, after the last
    part verifies and just before publication. It defaults to nowhere, so a front
    end with a log of its own (the GUI) never shows the password there.
    """
    log = warn if warn is not None else sys.stderr
    report = out if out is not None else sys.stdout

    def checked(_options: Options) -> Password:
        # The core checks every password, so no front end can skip the empty-password
        # rejection, and the warning about a weak one lands in the caller's sink.
        password = get_password(_options)
        passwords.check_strength(password, log)
        return password

    with collect(
        options.paths,
        excludes=options.all_excludes(),
        follow_symlinks=options.follow_symlinks,
        output=options.output,
        warn=log,
    ) as collection:
        if not collection.entries:
            raise InputError("nothing to archive: every input was skipped or excluded")
        if options.dry_run:
            print_dry_run(collection, options, report)
            return EXIT_OK
        results = write_archive(
            options, collection, checked, progress=progress, err=log, password_out=password_out
        )
        total = sum(r.size for r in results)
        noun = "part" if len(results) == 1 else "parts"
        names = ", ".join(r.path.name for r in results)
        print(
            f"zipseal: wrote {len(results)} {noun} ({total:,} bytes) in "
            f"{results[0].path.parent}: {names}",
            file=log,
        )
        return EXIT_OK
