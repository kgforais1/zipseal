"""Typed options for one archive job, shared by the CLI and the GUI (SPEC.md §4).

`cli.py` fills this from argparse; the GUI fills it from its widgets. Every field
has a default that matches the CLI's, so a front end only has to set what it
exposes. Nothing here can carry a password: the core takes one through the
`get_password` callback instead.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

DEFAULT_EXCLUDES = (".DS_Store", "._*", "Thumbs.db")

Order = Literal["path", "size"]


@dataclass
class Options:
    """Everything one run of the archive core needs.

    `excludes` holds the caller's globs. `default_excludes` decides whether the
    built-in junk-file globs are skipped on top of them, which is what
    `--no-default-excludes` turns off. `all_excludes()` combines the two in the
    order `collect` expects.
    """

    paths: list[Path]
    output: Path
    max_size: int | None = None
    level: int = 6
    excludes: list[str] = field(default_factory=list)
    default_excludes: bool = True
    follow_symlinks: bool = False
    hide_names: bool = False
    order: Order = "path"
    manifest: bool = False
    no_verify: bool = False
    force: bool = False
    dry_run: bool = False

    def all_excludes(self) -> list[str]:
        """Globs for `collect`: the defaults first, then the caller's."""
        patterns = [*DEFAULT_EXCLUDES] if self.default_excludes else []
        return patterns + [*self.excludes]
