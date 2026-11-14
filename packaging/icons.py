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

The command line accepts only `--target`. The SVG and both output directories
are the paths above, so an argument cannot redirect the download, the unpack,
or `resvg`. The download speaks https to GitHub's release hosts and does not
use `urlopen`, which would follow a redirect onto any scheme or host.
Unpacking writes the single bare `resvg` or `resvg.exe` member; archive paths
are not extracted.

The checksum check and the `.ico` packing take their inputs as arguments, so
`tests/test_packaging.py` drives them without a download and without a network.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import os
import platform
import shutil
import subprocess
import tarfile
import urllib.parse
import zipfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import IO, TYPE_CHECKING

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

# Exact hosts a resvg download may connect to. `github.com` answers first and
# redirects to the release-asset host; `objects.githubusercontent.com` is the
# older asset host. Anything else, including a `file:` redirect, stops the run.
RELEASE_HOSTS = (
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
)
DOWNLOAD_ATTEMPTS = 3
MAX_ASSET_BYTES = 32 * 1024 * 1024

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


def _pinned_release_url(asset_name: str) -> str:
    """Return the release URL for one pinned asset, or stop.

    The returned URL is built from the name stored in `RESVG_ASSETS`, not from
    the caller's string, so a different filename cannot change the request.
    """
    for name, _digest in RESVG_ASSETS.values():
        if name == asset_name:
            return f"{RESVG_URL}/{name}"
    raise SystemExit("packaging/icons.py: refusing to download a resvg asset that is not pinned")


def _allowlisted_host(host: str) -> str:
    """Return the allowlist's own host literal, or stop.

    A redirect supplies the host that is compared here. The value handed to
    the connection is the matching literal, so the request cannot use the
    redirect's string as the host.
    """
    if host not in RELEASE_HOSTS:
        raise SystemExit(
            "packaging/icons.py: the resvg download must stay on https to "
            "GitHub's release hosts; refused a different host"
        )
    if host == "github.com":
        return "github.com"
    if host == "release-assets.githubusercontent.com":
        return "release-assets.githubusercontent.com"
    if host == "objects.githubusercontent.com":
        return "objects.githubusercontent.com"
    raise SystemExit(
        "packaging/icons.py: the resvg download must stay on https to "
        "GitHub's release hosts; refused a different host"
    )


def _require_release_url(url: str) -> tuple[str, str]:
    """Return `(host, request target)` for one https hop, or stop.

    The request target is the path plus the query. A GitHub asset redirect
    carries a signed query, so callers must not log the URL. The host is one
    of the allowlist literals.
    """
    split = urllib.parse.urlsplit(url)
    host = split.hostname
    path_and_query = split.path + split.query
    unsafe_path = "\\" in split.path or any(part == ".." for part in split.path.split("/"))
    if (
        host is None
        or split.scheme != "https"
        or split.port not in (None, 443)
        or split.username is not None
        or split.password is not None
        or unsafe_path
        or any(character in path_and_query for character in "\r\n\0")
    ):
        scheme = split.scheme or "unknown"
        raise SystemExit(
            "packaging/icons.py: the resvg download must stay on https to "
            f"GitHub's release hosts; refused {scheme}"
        )
    target = split.path or "/"
    if split.query:
        target = f"{target}?{split.query}"
    return _allowlisted_host(host), target


def _read_limited(source: IO[bytes]) -> bytes:
    """Read at most `MAX_ASSET_BYTES`, and stop if the body is larger."""
    chunks: list[bytes] = []
    total = 0
    while True:
        block = source.read(1 << 20)
        if not block:
            return b"".join(chunks)
        total += len(block)
        if total > MAX_ASSET_BYTES:
            raise SystemExit("packaging/icons.py: resvg asset is larger than 32 MiB; refusing it")
        chunks.append(block)


def _https_get(url: str) -> tuple[int, str | None, bytes]:
    """GET one allowlisted https URL.

    Returns the status, the `Location` header, and the body. A non-200 body is
    discarded. Certificate verification stays at the library default.
    """
    host, target = _require_release_url(url)
    connection = http.client.HTTPSConnection(host, timeout=60)
    try:
        connection.request("GET", target, headers={"User-Agent": "zipseal-icons"})
        response = connection.getresponse()
        status = response.status
        location = response.getheader("Location")
        if status != 200:
            return status, location, b""
        return status, None, _read_limited(response)
    except (OSError, http.client.HTTPException) as exc:
        raise SystemExit(f"packaging/icons.py: the resvg download failed: {exc}") from exc
    finally:
        connection.close()


def _download_bytes(url: str) -> bytes:
    """Follow a short chain of https redirects and return the body.

    Each hop is checked again, including the host, before a connection opens.
    """
    current = url
    for _hop in range(DOWNLOAD_ATTEMPTS):
        # Check the hop before `_https_get` so a rejected redirect never connects.
        _require_release_url(current)
        status, location, body = _https_get(current)
        if status == 200:
            return body
        if status in {301, 302, 303, 307, 308} and location and location.startswith("https://"):
            current = location
            continue
        raise SystemExit(f"packaging/icons.py: the resvg download stopped with HTTP {status}")
    raise SystemExit("packaging/icons.py: the resvg download redirected too many times")


def _checked_destination(directory: Path, name: str) -> Path:
    """Return `directory / name` when `name` cannot leave `directory`."""
    if not name or name != Path(name).name or name in {".", ".."}:
        raise SystemExit("packaging/icons.py: refusing to write a path-like name")
    root = directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    candidate = root / name
    if candidate.is_symlink() or candidate.resolve().parent != root:
        raise SystemExit("packaging/icons.py: refusing to write outside the tool directory")
    return candidate


def _write_bytes(destination: Path, body: bytes) -> None:
    """Write `body` to `destination` as mode 0600, via a sibling `.partial` file."""
    partial = destination.with_name(destination.name + ".partial")
    try:
        partial.unlink(missing_ok=True)
        descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
        # `open` applies the umask, and `fchmod` is Unix-only. `chmod` sets
        # 0600 on the file the Windows build can run as well.
        os.chmod(partial, 0o600)
        partial.replace(destination)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise SystemExit(f"packaging/icons.py: could not write {destination.name}: {exc}") from exc


def download_asset(asset_name: str, destination: Path) -> Path:
    """Download one pinned release asset over https to `destination`.

    The asset name has to be one of the pinned filenames. The file is created
    mode 0600. `fetch_resvg` hashes it before anything unpacks or runs it.
    """
    url = _pinned_release_url(asset_name)
    target = _checked_destination(destination.parent, destination.name)
    _write_bytes(target, _download_bytes(url))
    return target


def _member_message(archive: Path, binary_name: str) -> str:
    """Return the error used when an archive is not the single expected binary."""
    return (
        f"packaging/icons.py: {archive.name} must contain exactly one bare "
        f"{binary_name} file; refusing to unpack anything else"
    )


def _zip_member(archive: Path, binary_name: str) -> bytes:
    """Return the bytes of the one zip member named exactly `binary_name`."""
    try:
        with zipfile.ZipFile(archive) as handle:
            matches = [
                info
                for info in handle.infolist()
                if info.filename == binary_name and not info.is_dir()
            ]
            if len(matches) != 1:
                raise SystemExit(_member_message(archive, binary_name))
            with handle.open(matches[0], "r") as source:
                return _read_limited(source)
    except zipfile.BadZipFile as exc:
        raise SystemExit(f"packaging/icons.py: {archive.name} is not a usable zip") from exc


def _tar_member(archive: Path, binary_name: str) -> bytes:
    """Return the bytes of the one regular tar member named exactly `binary_name`."""
    try:
        with tarfile.open(archive) as handle:
            matches = [
                member
                for member in handle.getmembers()
                if member.name == binary_name and member.isreg()
            ]
            if len(matches) != 1:
                raise SystemExit(_member_message(archive, binary_name))
            extracted = handle.extractfile(matches[0])
            if extracted is None:
                raise SystemExit(_member_message(archive, binary_name))
            with extracted:
                return _read_limited(extracted)
    except tarfile.TarError as exc:
        raise SystemExit(f"packaging/icons.py: {archive.name} is not a usable tar archive") from exc


def extract_binary(archive: Path, tools_dir: Path) -> Path:
    """Write the archive's bare resvg binary into `tools_dir` and return it.

    The member name must be exactly `resvg`, or `resvg.exe` for the Windows
    asset. Other members, including `..` paths, stay in the archive.
    """
    binary_name = "resvg.exe" if "-win-" in archive.name else "resvg"
    if archive.suffix == ".zip":
        payload = _zip_member(archive, binary_name)
    else:
        payload = _tar_member(archive, binary_name)
    destination = _checked_destination(tools_dir, binary_name)
    _write_bytes(destination, payload)
    destination.chmod(0o755)
    return destination


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


def path_argument(path: Path) -> str:
    """Return `path` as an argv element the build tool cannot treat as an option.

    resvg 0.50.0 treats a leading `-` as an option and does not take `--` as
    the end of options: it tries to open `--` as a file. A path that starts
    with `-`, or that contains a NUL, never reaches the tool.
    """
    text = str(path)
    if text.startswith("-") or "\0" in text:
        raise SystemExit(
            f"packaging/icons.py: refusing a path that looks like an option ({path.name})"
        )
    return text


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
            [
                path_argument(resvg),
                "-w",
                str(size),
                "-h",
                str(size),
                path_argument(svg),
                path_argument(target),
            ],
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
        [
            "iconutil",
            "--convert",
            "icns",
            "--output",
            path_argument(destination),
            path_argument(iconset),
        ],
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
    cannot read the SVG. Callers in this repository pass only `target`; the
    directory arguments exist so a test can point at a temporary tree.
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
    """Generate one target's icon rasters under `build/icons`.

    There is no path argument. Output directories and the SVG are the module
    paths, which keeps a command-line value out of the unpack step and out of
    `resvg`'s argument list.
    """
    parser = argparse.ArgumentParser(
        prog="icons.py",
        description="Generate the zipseal-gui icon rasters from src/zipseal/icon.svg.",
    )
    parser.add_argument("--target", choices=TARGETS, required=True, help="platform being built")
    args = parser.parse_args(argv)
    window_png = generate_icons(args.target)
    print(f"packaging/icons.py: wrote the {args.target} icons to {ICONS_DIR}")
    print(f"packaging/icons.py: {window_png} is the window and desktop PNG")


if __name__ == "__main__":
    main()
