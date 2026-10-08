"""Rebuild the local sample archives in sample-data/ (gitignored).

Usage: uv run python scripts/make_samples.py

Generates synthetic inputs that open normally (PNG images, text, a Unicode
name, an empty folder) in sample-data/input/, keeping any files you added
there yourself. Then it writes three sample sets with the password below:
a single zip, split parts with a manifest, and --hide-names parts.
"""

import os
import random
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

PASSWORD = "zipseal-sample-123"
ROOT = Path(__file__).resolve().parent.parent / "sample-data"
INPUT = ROOT / "input"
MAX_SIZE = "5MB"


def png(path: Path, width: int, height: int, seed: int) -> None:
    """Write a valid RGB PNG of colourful noise bands (barely compressible)."""
    rng = random.Random(seed)
    rows = []
    for y in range(height):
        base = (y * 255 // height, rng.randrange(256), 255 - y * 255 // height)
        row = bytearray([0])
        for _ in range(width):
            row += bytes((c + rng.randrange(-40, 40)) % 256 for c in base)
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(data)


def make_inputs() -> None:
    photos = INPUT / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    for old in photos.glob("img*.jpg"):  # earlier samples were random bytes, not images
        old.unlink()
    for i in range(1, 6):
        png(photos / f"generated-{i}.png", 600, 500, seed=i)
    (INPUT / "empty-folder").mkdir(exist_ok=True)
    (INPUT / "readme.txt").write_text("Hello from zipseal\n")
    (INPUT / "café-日本.txt").write_text("café\n")
    (INPUT / "notes").mkdir(exist_ok=True)
    (INPUT / "notes" / "long.txt").write_text("compressible line of text\n" * 20000)


def run(out: str, *flags: str) -> None:
    folder = ROOT / out
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    name = out.split("-", 1)[1]
    env = {**os.environ, "ZS_SAMPLE_PW": PASSWORD}
    subprocess.run(
        ["zipseal", str(INPUT), "-o", str(folder / f"{name}.zip"),
         "--password-env", "ZS_SAMPLE_PW", *flags],
        check=True,
        env=env,
    )  # fmt: skip


def main() -> None:
    make_inputs()
    run("1-single")
    run("2-split", "--max-size", MAX_SIZE, "--manifest")
    run("3-hidden", "--max-size", MAX_SIZE, "--hide-names")
    print(f"Samples are in {ROOT}. The password is in dev-docs/README.md.")


if __name__ == "__main__":
    main()
