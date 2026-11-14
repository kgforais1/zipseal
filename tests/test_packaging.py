"""Packaging guards, and the helpers a freeze can check without building an app."""

import importlib.util
import io
import platform
import plistlib
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_GLOBS = ["*.dmg", "*.msi", "*.exe", "*.AppImage", "*.tar.gz"]
ARTIFACT_NAMES = [
    "zipseal-gui-0.1.0-macos-arm64.dmg",
    "zipseal-gui-0.1.0-windows-x64.msi",
    "zipseal-gui.exe",
    "installer.AppImage",
    "zipseal-gui-0.1.0-linux-x86_64.tar.gz",
]
OUTPUT_ROOTS = ["dist/", "build/"]
ARTIFACT = "dist/0.1.0/zipseal-gui-0.1.0-macos-arm64.dmg"


def _load_guard():
    path = REPO_ROOT / "hooks" / "scripts" / "check_forbidden_paths.py"
    spec = importlib.util.spec_from_file_location("check_forbidden_paths", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_build():
    path = REPO_ROOT / "packaging" / "build.py"
    spec = importlib.util.spec_from_file_location("packaging_build", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_icons():
    path = REPO_ROOT / "packaging" / "icons.py"
    spec = importlib.util.spec_from_file_location("packaging_icons", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_guard = _load_guard()
read_patterns = _guard.read_patterns
glob_to_regex = _guard.glob_to_regex
main = _guard.main

_build = _load_build()
BUILD_PYTHON = _build.BUILD_PYTHON
collect_data_files = _build.collect_data_files
read_version = _build.read_version
render_info_plist = _build.render_info_plist
version_tuple = _build.version_tuple
render_windows_version_info = _build.render_windows_version_info
require_build_python = _build.require_build_python

_icons = _load_icons()


def _forbidden_patterns() -> list[str]:
    return read_patterns(REPO_ROOT / ".forbidden-paths")


def _gitignore_lines() -> list[str]:
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
    )


@pytest.mark.parametrize("glob", ARTIFACT_GLOBS)
def test_artifact_globs_are_forbidden(glob: str) -> None:
    patterns = _forbidden_patterns()
    assert glob in patterns


@pytest.mark.parametrize("glob", ARTIFACT_GLOBS)
def test_artifact_globs_are_gitignored(glob: str) -> None:
    assert glob in _gitignore_lines()


@pytest.mark.parametrize("root", OUTPUT_ROOTS)
def test_output_roots_are_forbidden_paths(root: str) -> None:
    patterns = _forbidden_patterns()
    assert root in patterns


@pytest.mark.parametrize("root", OUTPUT_ROOTS)
def test_output_roots_are_gitignored(root: str) -> None:
    lines = _gitignore_lines()
    assert root in lines


@pytest.mark.parametrize(("glob", "name"), list(zip(ARTIFACT_GLOBS, ARTIFACT_NAMES, strict=True)))
def test_artifact_globs_match_release_names(glob: str, name: str) -> None:
    matcher = glob_to_regex(glob)
    assert matcher.match(name)
    assert matcher.match(f"dist/0.1.0/{name}")


def test_tracked_artifact_under_dist_is_rejected(tmp_path: Path, capsys) -> None:
    root = tmp_path / "repo"
    artifact = root / ARTIFACT
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"not a real dmg")
    (root / ".forbidden-paths").write_text(
        (REPO_ROOT / ".forbidden-paths").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _git(root, "init")
    _git(root, "add", ARTIFACT)
    assert main(["--repo-root", str(root)]) == 1
    assert ARTIFACT in capsys.readouterr().err


def test_repo_without_artifacts_passes(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "cli.py").write_text("x = 1\n", encoding="utf-8")
    (root / ".forbidden-paths").write_text(
        (REPO_ROOT / ".forbidden-paths").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _git(root, "init")
    _git(root, "add", "src/cli.py")
    assert main(["--repo-root", str(root)]) == 0


def test_real_tree_is_clean() -> None:
    assert main(["--repo-root", str(REPO_ROOT)]) == 0


def test_read_version_matches_pyproject() -> None:
    expected = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert read_version() == expected["project"]["version"]


def test_version_reaches_every_platform_resource() -> None:
    version = read_version()
    plist = render_info_plist(version)
    assert plist["CFBundleShortVersionString"] == version
    assert plist["CFBundleVersion"] == version
    assert "@VERSION" not in "".join(plist.values())
    resource = render_windows_version_info(version)
    assert f"'{version}'" in resource
    assert version_tuple(version) in resource
    assert "@VERSION" not in resource


def test_linux_desktop_entry_has_required_keys() -> None:
    path = REPO_ROOT / "packaging" / "linux" / "zipseal-gui.desktop"
    fields = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip()
    assert fields["Name"] == "zipseal"
    assert fields["Exec"] == "zipseal-gui"
    assert fields["Icon"] == "zipseal-gui"
    assert fields["Terminal"] == "false"
    assert sorted(token for token in fields["Categories"].split(";") if token) == [
        "Security",
        "Utility",
    ]


def test_apprun_is_tracked_executable() -> None:
    """The index mode is what a checkout restores, not the working-tree bits."""
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-s", "--", "packaging/linux/AppRun"],
        check=True,
        capture_output=True,
        text=True,
    )
    mode, _blob, _stage, path = completed.stdout.split(maxsplit=3)
    assert path.strip() == "packaging/linux/AppRun"
    assert mode == "100755"


def test_macos_entitlements_plist_is_empty() -> None:
    path = REPO_ROOT / "packaging" / "macos" / "entitlements.plist"
    with path.open("rb") as handle:
        assert plistlib.load(handle) == {}


def test_collect_data_files_returns_both_icons() -> None:
    files = collect_data_files()
    assert ("src/zipseal/icon.svg", "zipseal") in files
    assert ("build/icons/icon.png", "zipseal") in files


def test_require_build_python_accepts_the_pinned_interpreter(monkeypatch) -> None:
    monkeypatch.setattr(platform, "python_version", lambda: BUILD_PYTHON)
    assert require_build_python() is None


def test_require_build_python_rejects_any_other_interpreter(monkeypatch) -> None:
    monkeypatch.setattr(platform, "python_version", lambda: "3.12.0")
    with pytest.raises(SystemExit) as excinfo:
        require_build_python()
    assert BUILD_PYTHON in str(excinfo.value)


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
    assert _icons.host_asset() in _icons.RESVG_ASSETS.values()
    assert _icons.RESVG_URL.endswith(f"v{_icons.RESVG_VERSION}")
    with pytest.raises(AssertionError, match="must not touch the network"):
        _icons.download_asset("resvg-win-x86_64.zip", tmp_path / "again.zip")


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


def test_download_writes_the_body_after_the_asset_redirect(tmp_path: Path, monkeypatch) -> None:
    def redirect_then_body(url: str) -> tuple[int, str | None, bytes]:
        if url.startswith("https://github.com/"):
            return 302, "https://release-assets.githubusercontent.com/asset?sig=1", b""
        return 200, None, b"pinned-bytes"

    monkeypatch.setattr(_icons, "_https_get", redirect_then_body)
    destination = tmp_path / "tools" / "resvg-linux-x86_64.tar.gz"
    written = _icons.download_asset("resvg-linux-x86_64.tar.gz", destination)
    assert written.read_bytes() == b"pinned-bytes"
    assert (written.stat().st_mode & 0o777) == 0o600
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
    assert (binary.stat().st_mode & 0o777) == 0o755
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
