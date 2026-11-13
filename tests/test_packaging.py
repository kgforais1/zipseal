"""The packaging guards must reject every build artifact before staging."""

import importlib.util
import subprocess
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


_guard = _load_guard()
read_patterns = _guard.read_patterns
glob_to_regex = _guard.glob_to_regex
main = _guard.main


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
