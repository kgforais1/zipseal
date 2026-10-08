"""Command-line entry point: argument parsing, password sources and exit codes."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from zipseal import __version__, passwords
from zipseal.errors import EXIT_INTERRUPT, EXIT_OK, UsageError, ZipsealError
from zipseal.passwords import Password
from zipseal.sizes import parse_size

DEFAULT_EXCLUDES = (".DS_Store", "._*", "Thumbs.db")


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
    )
    parser.add_argument("paths", metavar="PATH", nargs="+", type=Path, help="files or folders")
    parser.add_argument(
        "-o", "--output", required=True, type=Path, help="output name, such as bundle.zip"
    )
    parser.add_argument(
        "--max-size",
        type=_size,
        metavar="SIZE",
        help="cap per part, such as 25MB, 10MiB, 2G or plain bytes",
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
        help="deflate level (default 6; 0 stores without compression)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="skip matching files; repeatable",
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
        help="nest each part inside an encrypted outer zip so names are hidden",
    )
    parser.add_argument(
        "--manifest", action="store_true", help="add MANIFEST.txt listing every part's files"
    )
    parser.add_argument(
        "--no-verify", action="store_true", help="skip the decrypt check after writing"
    )
    parser.add_argument("--force", action="store_true", help="replace existing output files")
    parser.add_argument(
        "--dry-run", action="store_true", help="show the planned parts and write nothing"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    args = build_parser().parse_args(argv)
    args.excludes = ([] if args.no_default_excludes else list(DEFAULT_EXCLUDES)) + args.exclude
    return args


def get_password(args: argparse.Namespace) -> Password:
    if args.generate_password:
        password = passwords.generate()
    elif args.password_env:
        password = passwords.from_env(args.password_env)
    elif args.password_file:
        password = passwords.from_file(args.password_file)
    else:
        password = passwords.from_prompt()
    passwords.check_strength(password)
    return password


def run(args: argparse.Namespace) -> int:
    if not args.dry_run:
        get_password(args)
    raise UsageError("writing archives is not implemented yet")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(parse_args(argv)) or EXIT_OK
    except ZipsealError as exc:
        print(f"zipseal: error: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("zipseal: interrupted", file=sys.stderr)
        return EXIT_INTERRUPT
