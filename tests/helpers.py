import io
import os
from argparse import Namespace
from pathlib import Path

from stream_unzip import stream_unzip

from zipseal import cli
from zipseal.collect import Collection, collect
from zipseal.passwords import Password
from zipseal.pipeline import write_archive
from zipseal.write import PartResult

PASSWORD = "test-password-long"


def make_tree(root: Path, files: dict[str, bytes | str]) -> None:
    for rel, data in files.items():
        p = root / rel
        if rel.endswith("/"):
            p.mkdir(parents=True, exist_ok=True)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data.encode() if isinstance(data, str) else data)


def args_for(inputs: list[Path], output: Path, *extra: str) -> Namespace:
    return cli.parse_args([*map(str, inputs), "-o", str(output), *extra])


def collect_for(args: Namespace) -> Collection:
    return collect(
        args.paths,
        excludes=args.excludes,
        follow_symlinks=args.follow_symlinks,
        output=args.output,
        warn=io.StringIO(),
    )


def archive(
    inputs: list[Path], output: Path, *extra: str, password: str = PASSWORD
) -> list[PartResult]:
    args = args_for(inputs, output, *extra)
    with collect_for(args) as c:
        return write_archive(args, c, lambda _: Password(password), err=io.StringIO())


def extract(path: Path, password: str = PASSWORD) -> dict[str, bytes]:
    with open(path, "rb") as fh:
        data = fh.read()
    out: dict[str, bytes] = {}
    for name, _, chunks in stream_unzip([data], password=password.encode()):
        out[name.decode()] = b"".join(chunks)
    return out


def leftovers(folder: Path) -> list[str]:
    return sorted(n for n in os.listdir(folder) if n.endswith(".partial") or "zipseal-" in n)
