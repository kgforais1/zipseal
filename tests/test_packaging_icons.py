"""Icon-toolchain checks that never download resvg or open a window.

`icons.py` is loaded by path. `packaging` must not be on pytest's pythonpath:
it would shadow the PyPI `packaging` distribution.
"""

import importlib.util
import io
import os
import platform
import tarfile
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_icons():
    """Load `packaging/icons.py` by path, as `test_packaging.py` loads `build.py`."""
    path = REPO_ROOT / "packaging" / "icons.py"
    spec = importlib.util.spec_from_file_location("packaging_icons", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_icons = _load_icons()


class _NoExecution:
    """Stand in for the `subprocess` module: any call fails the test."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, command, *args: object, **kwargs: object) -> None:
        self.commands.append([str(part) for part in command])
        raise AssertionError("a checksum mismatch must never execute the asset")


def _refuse_network(url: str) -> tuple[int, str | None, bytes]:
    """Stand in for the https download: a fetch inside a test fails the test."""
    raise AssertionError(f"a packaging icon test must not touch the network: {url}")


def test_checksum_mismatch_rejects_the_binary_without_running_it(tmp_path, monkeypatch) -> None:
    tools = tmp_path / "build" / "tools"
    tools.mkdir(parents=True)
    archive = tools / "resvg-macos-aarch64.zip"
    archive.write_bytes(b"a tiny fixture, not the resvg release archive")
    subprocess_module = _NoExecution()
    monkeypatch.setattr(_icons, "subprocess", subprocess_module)
    with pytest.raises(SystemExit) as excinfo:
        _icons.verify_asset(archive, "0" * 64)
    assert "resvg-macos-aarch64.zip" in str(excinfo.value)
    assert not archive.exists()
    assert subprocess_module.commands == []


def test_matching_checksum_accepts_the_archive(tmp_path: Path) -> None:
    archive = tmp_path / "resvg-linux-x86_64.tar.gz"
    archive.write_bytes(b"fixture archive bytes")
    digest = _icons.sha256_file(archive)
    assert _icons.verify_asset(archive, digest) == archive
    assert archive.exists()


def test_the_icon_helpers_run_without_the_network(tmp_path: Path, monkeypatch) -> None:
    """Checksum and asset lookup must not download, and the downloader is stubbed."""
    monkeypatch.setattr(_icons, "_https_get", _refuse_network)
    archive = tmp_path / "resvg-win-x86_64.zip"
    archive.write_bytes(b"fixture archive bytes")
    assert _icons.verify_asset(archive, _icons.sha256_file(archive)) == archive
    if _icons.host_key() in _icons.RESVG_ASSETS:
        assert _icons.host_asset() in _icons.RESVG_ASSETS.values()
    else:
        with pytest.raises(SystemExit, match="no pinned resvg"):
            _icons.host_asset()
    assert _icons.RESVG_URL.endswith(f"v{_icons.RESVG_VERSION}")
    with pytest.raises(AssertionError, match="must not touch the network"):
        _icons.download_asset("resvg-win-x86_64.zip", tmp_path / "again.zip")


def test_host_asset_rejects_an_unpinned_platform_without_the_network(monkeypatch) -> None:
    """An Intel Mac or an ARM Linux host has no pinned resvg, and must not fetch one."""
    monkeypatch.setattr(_icons, "host_key", lambda: ("darwin", "x86_64"))
    monkeypatch.setattr(_icons, "_https_get", _refuse_network)
    with pytest.raises(SystemExit, match="no pinned resvg"):
        _icons.host_asset()


def test_pinned_resvg_assets_are_sha256_digests() -> None:
    for (_system, _machine), (asset, digest) in _icons.RESVG_ASSETS.items():
        assert asset.startswith("resvg-")
        assert asset.endswith(".zip") or asset.endswith(".tar.gz")
        assert len(digest) == 64
        assert digest == digest.lower()
        assert all(character in "0123456789abcdef" for character in digest)


def test_pack_ico_writes_the_ico_under_the_directory_it_is_given(tmp_path: Path) -> None:
    pytest.importorskip("PIL", reason="Pillow is in the build dependency group, not the test group")
    from PIL import Image

    icons_dir = tmp_path / "build" / "icons"
    icons_dir.mkdir(parents=True)
    source = icons_dir / "icon-256.png"
    Image.new("RGBA", (256, 256), (0, 0, 0, 0)).save(source)
    ico = _icons.pack_ico([source], icons_dir / "icon.ico")
    assert ico == icons_dir / "icon.ico"
    assert ico.is_relative_to(tmp_path)
    assert not list((REPO_ROOT / "src").rglob("*.ico"))
    assert not list((REPO_ROOT / "src").rglob("*.png"))
    with Image.open(ico) as packed:
        assert packed.format == "ICO"
    directory = ico.read_bytes()
    assert directory[:4] == b"\x00\x00\x01\x00"
    entries = int.from_bytes(directory[4:6], "little")
    assert entries == len(_icons.ICO_SIZES)
    # A directory entry stores 0 for 256, the one size that does not fit a byte.
    widths = {directory[6 + index * 16] for index in range(entries)}
    assert widths == {0 if size == 256 else size for size in _icons.ICO_SIZES}


def test_icon_cli_accepts_only_a_target() -> None:
    """A path flag must be rejected before any download or render starts."""
    with pytest.raises(SystemExit) as excinfo:
        _icons.main(["--target", "linux", "--tools-dir", "elsewhere"])
    assert excinfo.value.code == 2


def test_release_url_refuses_a_non_https_scheme() -> None:
    with pytest.raises(SystemExit) as excinfo:
        _icons._require_release_url("file:///etc/passwd")
    assert "file" in str(excinfo.value)


def test_release_url_refuses_userinfo_and_a_foreign_host() -> None:
    with pytest.raises(SystemExit):
        _icons._require_release_url("https://user@localhost/resvg")
    with pytest.raises(SystemExit) as excinfo:
        _icons._require_release_url("https://evil.example/resvg")
    assert "different host" in str(excinfo.value)


def test_release_url_accepts_the_asset_host() -> None:
    host, target = _icons._require_release_url(
        "https://release-assets.githubusercontent.com/github-production-release-asset/1?sig=1"
    )
    assert host == "release-assets.githubusercontent.com"
    assert target == "/github-production-release-asset/1?sig=1"


def test_download_refuses_an_unpinned_asset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(_icons, "_https_get", _refuse_network)
    with pytest.raises(SystemExit) as excinfo:
        _icons.download_asset("../resvg", tmp_path / "out")
    assert "not pinned" in str(excinfo.value)


def test_download_does_not_follow_a_redirect_off_github(tmp_path: Path, monkeypatch) -> None:
    """A 302 to another host is refused before a second connection."""
    calls: list[str] = []

    def redirect_once(url: str) -> tuple[int, str | None, bytes]:
        calls.append(url)
        return 302, "https://evil.example/resvg", b""

    monkeypatch.setattr(_icons, "_https_get", redirect_once)
    destination = tmp_path / "tools" / "resvg-linux-x86_64.tar.gz"
    with pytest.raises(SystemExit) as excinfo:
        _icons.download_asset("resvg-linux-x86_64.tar.gz", destination)
    assert "different host" in str(excinfo.value)
    assert len(calls) == 1
    assert not destination.exists()


def _assert_created_mode(path: Path, mode: int) -> None:
    """Check a created file's mode.

    Windows `chmod` only toggles the read-only flag, so an exact `0o600` or
    `0o755` comparison fails there after a successful write. POSIX keeps the
    exact bits. On Windows the file must still be writable.
    """
    if platform.system() == "Windows":
        assert os.access(path, os.W_OK)
        return
    assert (path.stat().st_mode & 0o777) == mode


def test_download_writes_the_body_after_the_asset_redirect(tmp_path: Path, monkeypatch) -> None:
    def redirect_then_body(url: str) -> tuple[int, str | None, bytes]:
        if url.startswith("https://github.com/"):
            return 302, "https://release-assets.githubusercontent.com/asset?sig=1", b""
        return 200, None, b"pinned-bytes"

    monkeypatch.setattr(_icons, "_https_get", redirect_then_body)
    destination = tmp_path / "tools" / "resvg-linux-x86_64.tar.gz"
    written = _icons.download_asset("resvg-linux-x86_64.tar.gz", destination)
    assert written.read_bytes() == b"pinned-bytes"
    _assert_created_mode(written, 0o600)
    assert not written.with_name(written.name + ".partial").exists()


def test_download_stops_on_http_404(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(_icons, "_https_get", lambda url: (404, None, b""))
    destination = tmp_path / "resvg-linux-x86_64.tar.gz"
    with pytest.raises(SystemExit) as excinfo:
        _icons.download_asset("resvg-linux-x86_64.tar.gz", destination)
    assert "404" in str(excinfo.value)
    assert not destination.exists()


def test_extract_writes_only_the_bare_zip_member(tmp_path: Path) -> None:
    """A `..` member stays in the archive and is not written beside the tools dir."""
    tools = tmp_path / "tools"
    tools.mkdir()
    archive = tools / "resvg-macos-aarch64.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("resvg", b"real")
        handle.writestr("README", b"notes")
        handle.writestr(zipfile.ZipInfo("../escaped"), b"nope")
    binary = _icons.extract_binary(archive, tools)
    assert binary.read_bytes() == b"real"
    assert binary.name == "resvg"
    _assert_created_mode(binary, 0o755)
    assert binary.is_relative_to(tools)
    assert not (tools / "README").exists()
    assert not (tmp_path / "escaped").exists()


def test_extract_reads_the_windows_binary_name(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    archive = tools / "resvg-win-x86_64.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("resvg.exe", b"win")
    binary = _icons.extract_binary(archive, tools)
    assert binary.name == "resvg.exe"
    assert binary.read_bytes() == b"win"


def test_extract_rejects_a_tar_that_has_no_bare_binary(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    archive = tools / "resvg-linux-x86_64.tar.gz"
    payload = b"nope"
    info = tarfile.TarInfo("../resvg")
    info.size = len(payload)
    info.type = tarfile.REGTYPE
    with tarfile.open(archive, "w:gz") as handle:
        handle.addfile(info, io.BytesIO(payload))
    with pytest.raises(SystemExit) as excinfo:
        _icons.extract_binary(archive, tools)
    assert "bare resvg" in str(excinfo.value)
    assert not (tmp_path / "resvg").exists()
    assert not (tools / "resvg").exists()


def test_extract_rejects_a_corrupt_zip(tmp_path: Path) -> None:
    archive = tmp_path / "resvg-macos-aarch64.zip"
    archive.write_bytes(b"not a zip")
    with pytest.raises(SystemExit) as excinfo:
        _icons.extract_binary(archive, tmp_path)
    assert "not a usable zip" in str(excinfo.value)


def test_render_refuses_a_path_that_looks_like_an_option(tmp_path: Path, monkeypatch) -> None:
    calls = _NoExecution()
    monkeypatch.setattr(_icons, "subprocess", calls)
    with pytest.raises(SystemExit) as excinfo:
        _icons.render_pngs(Path("-in.svg"), tmp_path, tmp_path / "resvg", sizes=[16])
    assert calls.commands == []
    assert "looks like an option" in str(excinfo.value)
