"""PyPI packaging contracts: the readme renders on PyPI, and uploads recover."""

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
CODE_SPAN_RE = re.compile(r"`[^`]*`")
INLINE_RE = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+[^)]*)?\)")
REFERENCE_RE = re.compile(r"^\s*\[[^\]]+\]:\s*<?([^\s>]+)>?", re.MULTILINE)
HTML_RE = re.compile(r"""(?:href|src)=["']([^"']+)["']""")


def _workflow() -> Any:
    path = REPO_ROOT / ".github" / "workflows" / "pypi.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _link_targets(text: str) -> list[str]:
    """Every link, image, reference and HTML target outside code."""
    text = FENCE_RE.sub("", text)
    text = CODE_SPAN_RE.sub("", text)
    return INLINE_RE.findall(text) + REFERENCE_RE.findall(text) + HTML_RE.findall(text)


def test_link_guard_sees_nested_badges_references_and_html() -> None:
    """The readme guard also checks an outer badge link and non-paren targets."""
    text = (
        "[![alt](https://img.example/badge.svg)](LICENSE)\n"
        "[guide][docs]\n\n"
        "[docs]: user-docs/gui.md\n"
        '<a href="user-docs/cli.md">CLI</a>\n'
        "```\n[ignored](inside-a-fence.md)\n```\n"
        "`[ignored](inside-a-code-span.md)`\n"
    )
    assert _link_targets(text) == [
        "https://img.example/badge.svg",
        "LICENSE",
        "user-docs/gui.md",
        "user-docs/cli.md",
    ]


def test_readme_links_resolve_on_pypi() -> None:
    """PyPI resolves readme links against the project page, so none are relative."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    targets = _link_targets(readme)
    assert targets
    relative = [target for target in targets if not target.startswith(("https://", "#", "mailto:"))]
    assert relative == []


def test_pypi_publish_concurrency_is_per_tag() -> None:
    """A waiting approval for one version is not replaced by the next release."""
    concurrency = _workflow()["concurrency"]
    assert concurrency["group"] == (
        "pypi-publish-${{ github.event.release.tag_name || inputs.tag }}"
    )
    assert concurrency["cancel-in-progress"] is False


def test_pypi_publish_rerun_uploads_only_missing_files() -> None:
    """A failed partial upload can be completed without a version bump."""
    steps = _workflow()["jobs"]["publish"]["steps"]
    publish = [
        step
        for step in steps
        if str(step.get("uses", "")).startswith("pypa/gh-action-pypi-publish@")
    ]
    assert len(publish) == 1
    assert publish[0]["with"]["skip-existing"] is True
    assert publish[0]["with"]["attestations"] is True
