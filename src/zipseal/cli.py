"""Command-line entry point: argument parsing, password sources and exit codes.

This module is one front end on top of `job.run_job`, the core the CLI and the
GUI share. It turns argv into `Options` and points the core's `warn` sink at
stderr; it holds no archive logic.
"""

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from zipseal import __version__, passwords
from zipseal.errors import EXIT_INTERRUPT, EXIT_OK, UsageError, ZipsealError
from zipseal.job import run_job
from zipseal.options import DEFAULT_EXCLUDES, Options
from zipseal.passwords import Password
from zipseal.sizes import parse_size

EPILOG = """\
examples:
  zipseal reports/ notes.txt -o bundle.zip --generate-password
  zipseal reports/ -o bundle.zip --max-size 20MB          # parts for email
  zipseal reports/ -o bundle.zip --max-size 20MB --hide-names
  zipseal reports/ -o bundle.zip --max-size 20MB --dry-run

passwords:
  There is no option that takes the password itself, because it would end up
  in shell history and the process list. Without a password option, zipseal
  prompts twice. Send the password through a different channel than the zip.

output:
  One part keeps the -o name. Several are named NAME-partNN-of-MM.zip, and
  each one opens on its own. Existing files are never overwritten without
  --force. Every part is verified before it gets its final name.

opening the archives:
  Finder (macOS 11+), 7-Zip, Keka, or `tar -xf FILE` (prompts for the password).
  macOS /usr/bin/unzip cannot open AES zips. With --hide-names, open the part
  with the password, then open payload.zip inside it.

exit codes:
  0 success, 1 usage error, 2 input error (missing path, name collision,
  file too large for --max-size), 3 write or verify failure, 130 interrupted.
"""


class _Parser(argparse.ArgumentParser):
    """Report usage errors with exit 1 (SPEC.md §4), not argparse's default 2."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def _size(text: str) -> int:
    try:
        return parse_size(text)
    except UsageError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="zipseal",
        description=(
            "Write files and folders into AES-256 encrypted zips, optionally split "
            "into self-contained parts that each stay under a size cap."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", metavar="PATH", nargs="+", type=Path, help="files or folders")
    parser.add_argument(
        "-o", "--output", required=True, type=Path, help="output name, such as bundle.zip"
    )
    parser.add_argument(
        "--max-size",
        type=_size,
        metavar="SIZE",
        help="cap per part: plain bytes, KB/MB/GB/TB (powers of 10) or KiB/MiB/GiB/TiB",
    )

    pw = parser.add_mutually_exclusive_group()
    pw.add_argument(
        "--password-prompt",
        action="store_true",
        help="prompt twice for the password (the default)",
    )
    pw.add_argument("--password-env", metavar="VAR", help="read the password from VAR")
    pw.add_argument(
        "--password-file", metavar="PATH", type=Path, help="read the first line of PATH"
    )
    pw.add_argument(
        "--generate-password",
        action="store_true",
        help="generate a random password and print it once to stderr",
    )

    parser.add_argument(
        "--level",
        type=int,
        choices=range(10),
        default=6,
        metavar="0-9",
        help="deflate level (default 6; 0 = no compression)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="skip names matching GLOB (or archive paths, if GLOB has a /); repeatable",
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help=f"do not skip {', '.join(DEFAULT_EXCLUDES)}",
    )
    parser.add_argument(
        "--follow-symlinks", action="store_true", help="follow symlinks instead of skipping them"
    )
    parser.add_argument(
        "--order",
        choices=("path", "size"),
        default="path",
        help="path keeps folders together (default); size packs into fewer parts",
    )
    parser.add_argument(
        "--hide-names",
        action="store_true",
        help="hide file names, sizes and dates: each part holds one encrypted payload.zip",
    )
    parser.add_argument(
        "--manifest", action="store_true", help="add MANIFEST.txt listing every part's files"
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip decrypting each part after writing (the size cap is still checked)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace existing outputs; they are restored if the run fails",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show the planned parts and write nothing"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def get_password(args: argparse.Namespace) -> Password:
    """Pick a password source (SPEC.md §4). Its strength is checked by the core."""
    if args.generate_password:
        return passwords.generate()
    if args.password_env:
        return passwords.from_env(args.password_env)
    if args.password_file:
        return passwords.from_file(args.password_file)
    return passwords.from_prompt()


@dataclass(frozen=True)
class Command:
    """One parsed command line: what to archive, and where the password comes from."""

    options: Options
    get_password: Callable[[Options], Password]


def options_from_args(args: argparse.Namespace) -> Options:
    """Build the core's `Options` from argparse's namespace."""
    return Options(
        paths=list(args.paths),
        output=args.output,
        max_size=args.max_size,
        level=args.level,
        excludes=list(args.exclude),
        default_excludes=not args.no_default_excludes,
        follow_symlinks=args.follow_symlinks,
        hide_names=args.hide_names,
        order=args.order,
        manifest=args.manifest,
        no_verify=args.no_verify,
        force=args.force,
        dry_run=args.dry_run,
    )


def parse_args(argv: Sequence[str] | None = None) -> Command:
    """Parse argv into a `Command` for `run`."""
    args = build_parser().parse_args(argv)
    return Command(options_from_args(args), lambda _: get_password(args))


def run(command: Command) -> int:
    """Run the parsed command line through the shared core, warnings to stderr."""
    return run_job(command.options, command.get_password)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(parse_args(argv)) or EXIT_OK
    except ZipsealError as exc:
        print(f"zipseal: error: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("zipseal: interrupted", file=sys.stderr)
        return EXIT_INTERRUPT
