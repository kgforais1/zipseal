"""Generate the app icon rasters at build time from the repository's SVG.

`src/zipseal/icon.svg` is the only icon source in the repository, and nothing
raster is committed - `*.png` is a forbidden path - so every raster a freeze
needs is produced here, into `build/icons/`, which `.gitignore` covers.

One pinned toolchain (plan: GUI executables, Decision 7). The official `resvg`
release binary renders the PNGs, Pillow from the `build` dependency group packs
the multi-size `.ico`, and macOS `iconutil` turns an `.iconset` into the
`.icns` on the macOS runner. `icon.png` is both the fallback
`gui_view.set_icon` reads when Tk cannot load the SVG and the Linux desktop
icon. `resvg` reaches `build/tools/` through a pinned URL and a sha256 that is
checked before the archive is ever extracted or its binary executed.

The checksum check and the `.ico` packing take their inputs as arguments, so
`tests/test_packaging.py` drives them without a download and without a network.
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

PACKAGING_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGING_DIR.parent
SVG_SOURCE = REPO_ROOT / "src" / "zipseal" / "icon.svg"
TOOLS_DIR = REPO_ROOT / "build" / "tools"
ICONS_DIR = REPO_ROOT / "build" / "icons"

TARGETS = ("macos", "windows", "linux")

RESVG_VERSION = "0.50.0"
RESVG_URL = f"https://github.com/linebender/resvg/releases/download/v{RESVG_VERSION}"

# resvg publishes no checksum file with a release (checked 2026-11-13 against
# the v0.50.0 assets), so each sha256 below was computed here with
# `shasum -a 256` on the asset this repository downloaded from that release,
# and each asset's size matched what the GitHub release API reported. They are
# the published release binaries rather than static ones: the Linux asset links
# glibc and the macOS asset links libSystem, and the Linux build runs in the
# pinned container that provides the glibc it expects.
RESVG_ASSETS: dict[tuple[str, str], tuple[str, str]] = {
    ("darwin", "arm64"): (
        "resvg-macos-aarch64.zip",
        "8155b569f2b93723ba3645b53536eead3b591c8faf62bdaafd3033ba37838837",
    ),
    ("windows", "x86_64"): (
        "resvg-win-x86_64.zip",
        "e4817e40ac63d3eb5c9e5762526cf6cc91f0cc108de38cd09dd60be765184efd",
    ),
    ("linux", "x86_64"): (
        "resvg-linux-x86_64.tar.gz",
        "5d1c9ffd43c82fb802d92cef8100055c612cd3e248d5a787c20079293a456e21",
    ),
}

PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICONSET_BASES = (16, 32, 128, 256, 512)
WINDOW_PNG_SIZE = 512

ICON_PNG = "icon.png"
ICON_ICO = "icon.ico"
ICON_ICNS = "icon.icns"


def png_name(size: int) -> str:
    """Return the file name a render of one size is written to."""
    return f"icon-{size}.png"


def sha256_file(path: Path) -> str:
    """Return a file's sha256 as hex, reading it in fixed-size blocks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_asset(path: Path, expected: str) -> Path:
    """Return the path when its digest matches the pin, or delete it and fail.

    A download that was truncated or swapped in flight must never reach a
    render, so the archive is hashed before anything extracts or runs it, and a
    mismatch removes the file so the next run fetches it again.
    """
    actual = sha256_file(path)
    if actual == expected:
        return path
    path.unlink(missing_ok=True)
    raise SystemExit(
        f"packaging/icons.py: {path.name} has sha256 {actual} but the pin is "
        f"{expected}; deleted it and stopped before anything ran it"
    )


def host_key() -> tuple[str, str]:
    """Return the `(system, machine)` pair the pinned assets are keyed by."""
    aliases = {"amd64": "x86_64", "x86-64": "x86_64", "aarch64": "arm64"}
    machine = platform.machine().lower()
    return platform.system().lower(), aliases.get(machine, machine)


def host_asset() -> tuple[str, str]:
    """Return the pinned resvg asset name and digest for the build host."""
    key = host_key()
    try:
        return RESVG_ASSETS[key]
    except KeyError:
        raise SystemExit(
            f"packaging/icons.py: no pinned resvg {RESVG_VERSION} asset for {key}; "
            "add one to RESVG_ASSETS with a sha256 computed from the release asset"
        ) from None


def download_asset(asset_name: str, destination: Path) -> Path:
    """Fetch one release asset into the tools directory."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = f"{RESVG_URL}/{asset_name}"
    with urllib.request.urlopen(url) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return destination


def extract_binary(archive: Path, tools_dir: Path) -> Path:
    """Unpack a resvg release archive and return the executable it contains."""
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as handle:
            handle.extractall(tools_dir)
        binary = tools_dir / ("resvg.exe" if "-win-" in archive.name else "resvg")
    else:
        with tarfile.open(archive) as handle:
            handle.extractall(tools_dir, filter="data")
        binary = tools_dir / "resvg"
    binary.chmod(0o755)
    return binary


def fetch_resvg(tools_dir: Path = TOOLS_DIR) -> Path:
    """Return the host platform's resvg binary, fetching it only once.

    The archive is the pinned artifact, so its digest is checked on every run
    and the extracted binary only ever comes from an archive that matched it.
    """
    asset_name, digest = host_asset()
    archive = tools_dir / asset_name
    if not archive.exists():
        download_asset(asset_name, archive)
    verify_asset(archive, digest)
    return extract_binary(archive, tools_dir)


def run(command: list[str], what: str) -> None:
    """Run a build tool, reporting a failure as one line with its output."""
    try:
        subprocess.run(command, check=True, capture_output=True)
    except OSError as exc:
        raise SystemExit(f"packaging/icons.py: {what} could not run: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", "replace").strip()
        raise SystemExit(f"packaging/icons.py: {what} failed: {detail}") from exc


def render_pngs(
    svg: Path, icons_dir: Path, resvg: Path, sizes: Iterable[int] = PNG_SIZES
) -> dict[int, Path]:
    """Render the SVG at every size, and return each size's PNG path."""
    icons_dir.mkdir(parents=True, exist_ok=True)
    rendered: dict[int, Path] = {}
    for size in sizes:
        target = icons_dir / png_name(size)
        run(
            [str(resvg), "-w", str(size), "-h", str(size), str(svg), str(target)],
            f"resvg {RESVG_VERSION} rendering {size}px",
        )
        rendered[size] = target
    return rendered


def pack_ico(sources: Sequence[Path], destination: Path) -> Path:
    """Pack rendered PNGs into a multi-size Windows `.ico` with Pillow.

    Pillow builds every `.ico` entry from one image, so the sources only have
    to include a PNG at least as large as the biggest entry. The output path is
    the caller's, which keeps every raster under `build/icons/` and none beside
    the SVG in `src/`.
    """
    from PIL import Image

    if not sources:
        raise SystemExit("packaging/icons.py: no rendered PNG to pack into an .ico")
    frames: list[Image.Image] = []
    for path in sources:
        with Image.open(path) as frame:
            frames.append(frame.copy())
    base = max(frames, key=lambda frame: frame.width)
    destination.parent.mkdir(parents=True, exist_ok=True)
    base.save(destination, format="ICO", sizes=[(size, size) for size in ICO_SIZES])
    return destination


def iconset_entries() -> list[tuple[str, int]]:
    """Return the `iconutil` file names and the pixel size each must hold."""
    entries = []
    for base in ICONSET_BASES:
        entries.append((f"icon_{base}x{base}.png", base))
        entries.append((f"icon_{base}x{base}@2x.png", base * 2))
    return entries


def pack_icns(rendered: dict[int, Path], icons_dir: Path, destination: Path) -> Path:
    """Assemble an `.iconset` from the rendered PNGs and convert it to `.icns`."""
    iconset = icons_dir / "icon.iconset"
    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir(parents=True, exist_ok=True)
    for name, size in iconset_entries():
        shutil.copyfile(rendered[size], iconset / name)
    run(
        ["iconutil", "--convert", "icns", "--output", str(destination), str(iconset)],
        "iconutil building the macOS icns",
    )
    return destination


def generate_icons(
    target: str,
    *,
    icons_dir: Path = ICONS_DIR,
    tools_dir: Path = TOOLS_DIR,
    svg: Path = SVG_SOURCE,
) -> Path:
    """Render every raster the freeze needs, and return the window PNG path.

    Every target gets the PNGs and the `.ico`; a macOS target also gets the
    `.icns`. This fails with an explicit message if `icon.png` is missing when
    it returns, because the frozen window would then have no fallback when Tk
    cannot read the SVG.
    """
    if target not in TARGETS:
        choices = ", ".join(TARGETS)
        raise SystemExit(f"packaging/icons.py: unknown target {target!r}; expected {choices}")
    if not svg.exists():
        raise SystemExit(f"packaging/icons.py: {svg} is missing, and it is the only icon source")
    resvg = fetch_resvg(tools_dir)
    rendered = render_pngs(svg, icons_dir, resvg)
    pack_ico([rendered[size] for size in ICO_SIZES], icons_dir / ICON_ICO)
    if target == "macos":
        pack_icns(rendered, icons_dir, icons_dir / ICON_ICNS)
    else:
        # A previous macOS run must not leave an icns behind for another target.
        (icons_dir / ICON_ICNS).unlink(missing_ok=True)
    window_png = icons_dir / ICON_PNG
    shutil.copyfile(rendered[WINDOW_PNG_SIZE], window_png)
    if not window_png.exists():
        raise SystemExit(
            f"packaging/icons.py: {window_png} is missing after generating the icons for "
            f"{target}, and the frozen window needs it as the SVG fallback"
        )
    return window_png


def main(argv: list[str] | None = None) -> None:
    """Generate one target's icon rasters, and report the paths it wrote."""
    parser = argparse.ArgumentParser(
        prog="icons.py",
        description="Generate the zipseal-gui icon rasters from src/zipseal/icon.svg.",
    )
    parser.add_argument("--target", choices=TARGETS, required=True, help="platform being built")
    parser.add_argument("--icons-dir", type=Path, default=ICONS_DIR, help="where the rasters go")
    parser.add_argument("--tools-dir", type=Path, default=TOOLS_DIR, help="where resvg is kept")
    parser.add_argument("--svg", type=Path, default=SVG_SOURCE, help="the icon source to render")
    args = parser.parse_args(argv)
    window_png = generate_icons(
        args.target, icons_dir=args.icons_dir, tools_dir=args.tools_dir, svg=args.svg
    )
    print(f"packaging/icons.py: wrote the {args.target} icons to {args.icons_dir}")
    print(f"packaging/icons.py: {window_png} is the window and desktop PNG")


if __name__ == "__main__":
    main()
