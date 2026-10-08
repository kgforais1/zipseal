"""Part names, existing-output checks, no-clobber publication and cleanup (SPEC.md §6.5, §6.8)."""

import os
import re
import secrets
import sys
from pathlib import Path
from typing import TextIO

from zipseal.errors import WriteError


class Output:
    """Owns every file this run creates. `cleanup()` removes whatever was not published."""

    def __init__(self, output: Path, *, force: bool, warn: TextIO | None = None) -> None:
        self.output = Path(os.path.abspath(output))
        self.dir = self.output.parent
        self.stem = self.output.stem
        self.suffix = self.output.suffix
        self.force = force
        self.warn = warn or sys.stderr
        self.token = secrets.token_hex(4)
        self.partials: list[Path] = []
        self._part_re = re.compile(
            re.escape(self.stem) + r"-part\d+-of-\d+" + re.escape(self.suffix)
        )

    # ── before writing ────────────────────────────────────────────────────────

    def existing(self) -> list[Path]:
        """The -o name and any old part names for it that exist now."""
        found = []
        try:
            names = os.listdir(self.dir)
        except OSError as exc:
            raise WriteError(f"{self.dir}: {exc.strerror}") from None
        for name in sorted(names):
            if name == self.output.name or self._part_re.fullmatch(name):
                found.append(self.dir / name)
        return found

    def preflight(self) -> None:
        """Fail early if outputs exist (without --force) or the folder cannot hold them."""
        if not self.dir.is_dir():
            raise WriteError(f"{self.dir}: output folder does not exist")
        if not self.force:
            clash = self.existing()
            if clash:
                listing = "\n".join(f"  {p}" for p in clash)
                raise WriteError(f"output files already exist (use --force):\n{listing}")
        self._check_hard_links()

    def _check_hard_links(self) -> None:
        probe = self.dir / f".{self.stem}.zipseal-probe-{self.token}"
        link = self.dir / f".{self.stem}.zipseal-probe-{self.token}.link"
        try:
            fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        except OSError as exc:
            raise WriteError(f"{self.dir}: cannot create files here: {exc.strerror}") from None
        try:
            os.link(probe, link)
        except OSError:
            raise WriteError(
                f"{self.dir}: this filesystem does not support hard links, which zipseal "
                "needs to publish files without overwriting anything"
            ) from None
        finally:
            for p in (probe, link):
                try:
                    os.unlink(p)
                except FileNotFoundError:
                    pass

    # ── while writing ─────────────────────────────────────────────────────────

    def new_partial(self, number: int) -> Path:
        path = self.dir / f"{self.stem}-part{number:02d}{self.suffix}.partial"
        self.partials.append(path)
        return path

    def final_names(self, count: int) -> list[Path]:
        if count == 1:
            return [self.output]
        width = 2 if count <= 99 else 3
        return [
            self.dir / f"{self.stem}-part{i:0{width}d}-of-{count:0{width}d}{self.suffix}"
            for i in range(1, count + 1)
        ]

    # ── publication ───────────────────────────────────────────────────────────

    def publish(self, partials: list[Path], finals: list[Path]) -> None:
        """Hard-link each partial to its final name, never overwriting a file.

        With --force, existing final names are first moved to private backups,
        restored if anything fails before the last part is published, and deleted
        after it (the commit point).
        """
        backups: list[tuple[Path, Path]] = []
        published: list[Path] = []
        try:
            for partial, final in zip(partials, finals, strict=True):
                if self.force and os.path.lexists(final):
                    backup = final.with_name(f".{final.name}.zipseal-backup-{self.token}")
                    os.rename(final, backup)
                    backups.append((backup, final))
                try:
                    os.link(partial, final)
                except FileExistsError:
                    raise WriteError(
                        f"{final}: appeared while zipseal was running; not overwritten"
                    ) from None
                published.append(final)
                os.unlink(partial)
                self.partials.remove(partial)
        except BaseException as exc:
            self._rollback(published, backups)
            if isinstance(exc, OSError):
                raise WriteError(
                    f"publishing failed: {exc.strerror}; no archive was written"
                ) from None
            raise
        # Commit point: every part is published. Nothing below rolls back.
        leftover = []
        for backup, _ in backups:
            try:
                os.unlink(backup)
            except OSError:
                leftover.append(backup)
        if leftover:
            listing = "\n".join(f"  {p}" for p in leftover)
            print(
                f"zipseal: warning: could not delete old outputs kept as backups:\n{listing}",
                file=self.warn,
            )
        if self.force:
            stale = [p for p in self.existing() if p not in finals]
            if stale:
                listing = "\n".join(f"  {p}" for p in stale)
                print(
                    f"zipseal: warning: older part files remain and were not touched:\n{listing}",
                    file=self.warn,
                )

    def _rollback(self, published: list[Path], backups: list[tuple[Path, Path]]) -> None:
        for final in published:
            try:
                os.unlink(final)
            except OSError:
                pass
        for backup, final in backups:
            try:
                os.rename(backup, final)
            except OSError:
                print(f"zipseal: warning: could not restore {final} from {backup}", file=self.warn)

    def cleanup(self) -> None:
        for path in self.partials:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        self.partials.clear()
