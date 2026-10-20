"""Part names, existing-output checks, no-clobber publication and cleanup (SPEC.md §6.5, §6.8)."""

import os
import re
import secrets
import sys
from pathlib import Path
from typing import TextIO

from zipseal.errors import WriteError


def temp_name_re(stem: str, suffix: str) -> re.Pattern[str]:
    """Match this output's temporary files, current or left by an older version.

    The current name is `NAME-volumeNN.zip.temp`. Older versions wrote
    `NAME-volumeNN.zip.partial`, and before the -volume rename,
    `NAME-partNN.zip.partial`. No version ever wrote `NAME-partNN.zip.temp`,
    and every version numbered parts with at least two digits.
    """
    s = re.escape(suffix)
    return re.compile(
        re.escape(stem) + rf"(?:-volume\d{{2,}}{s}\.(?:temp|partial)|-part\d{{2,}}{s}\.partial)"
    )


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
        self.temps: list[Path] = []
        self._part_re = re.compile(
            re.escape(self.stem) + r"-volume\d+-of-\d+" + re.escape(self.suffix)
        )
        # Names from before the -volume rename. They never block a run and are
        # never replaced, but publication warns that they are still there.
        self._legacy_re = re.compile(
            re.escape(self.stem) + r"-part\d+-of-\d+" + re.escape(self.suffix)
        )
        # Leftover temporary files block a run, including older versions' names.
        self._temp_re = temp_name_re(self.stem, self.suffix)

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
        leftovers = [
            self.dir / n for n in sorted(os.listdir(self.dir)) if self._temp_re.fullmatch(n)
        ]
        if leftovers:
            listing = "\n".join(f"  {p}" for p in leftovers)
            raise WriteError(
                "temporary files from an earlier, interrupted run are in the way. Check them, "
                f"then delete them:\n{listing}"
            )
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

    def new_temp(self, number: int) -> tuple[Path, int]:
        """Create the next `.temp` file and return its path and open descriptor.

        The path is registered for cleanup only after this run has created it, so a
        failed create never deletes a file another run owns.
        """
        path = self.dir / f"{self.stem}-volume{number:02d}{self.suffix}.temp"
        fd = create_exclusive(path)
        self.temps.append(path)
        return path, fd

    def final_names(self, count: int) -> list[Path]:
        if count == 1:
            return [self.output]
        width = max(2, len(str(count)))  # same width for every part, so names sort
        return [
            self.dir / f"{self.stem}-volume{i:0{width}d}-of-{count:0{width}d}{self.suffix}"
            for i in range(1, count + 1)
        ]

    # ── publication ───────────────────────────────────────────────────────────

    def publish(self, temps: list[Path], finals: list[Path]) -> None:
        """Hard-link each `.temp` file to its final name, never overwriting a file.

        With --force, existing final names are first moved to private backups,
        restored if anything fails before the last part is published, and deleted
        after it (the commit point).
        """
        backups: list[tuple[Path, Path]] = []
        published: list[Path] = []
        clash: Path | None = None
        try:
            for temp, final in zip(temps, finals, strict=True):
                if self.force and os.path.lexists(final):
                    backup = final.with_name(f".{final.name}.zipseal-backup-{self.token}")
                    os.rename(final, backup)
                    backups.append((backup, final))
                try:
                    os.link(temp, final)
                except FileExistsError:
                    clash = final
                    raise
                published.append(final)
                os.unlink(temp)
                self.temps.remove(temp)
        except BaseException as exc:
            # Say "no archive" only if the rollback really removed every published part.
            outcome = (
                "no archive was written"
                if self._rollback(published, backups)
                else "a published part could not be removed, see the warning above"
            )
            if clash is not None:
                raise WriteError(
                    f"{clash}: appeared while zipseal was running; not overwritten, and {outcome}"
                ) from None
            if isinstance(exc, OSError):
                raise WriteError(f"publishing failed: {exc.strerror}; {outcome}") from None
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
        # Past the commit point, so a folder that cannot be listed only skips the warning.
        try:
            names = sorted(os.listdir(self.dir))
        except OSError:
            names = []
        stale = [
            self.dir / n
            for n in names
            if (
                self.force
                and (n == self.output.name or self._part_re.fullmatch(n))
                and self.dir / n not in finals
            )
            or self._legacy_re.fullmatch(n)
        ]
        if stale:
            listing = "\n".join(f"  {p}" for p in stale)
            print(
                f"zipseal: warning: older part files remain and were not touched:\n{listing}",
                file=self.warn,
            )

    def _rollback(self, published: list[Path], backups: list[tuple[Path, Path]]) -> bool:
        """Undo a failed publication. Returns whether every published part is gone."""
        removed = True
        for final in published:
            try:
                os.unlink(final)
            except OSError:
                removed = False
                print(
                    f"zipseal: warning: could not remove {final}; it is a complete, "
                    "verified part of the failed run",
                    file=self.warn,
                )
        for backup, final in backups:
            try:
                os.rename(backup, final)
            except OSError:
                print(f"zipseal: warning: could not restore {final} from {backup}", file=self.warn)
        return removed

    def cleanup(self) -> None:
        """Delete this run's `.temp` files, and warn about any that stay.

        It runs while another error or a cancel is on its way out, so a failed
        delete is a warning here and never replaces that error.
        """
        kept: list[str] = []
        for path in self.temps:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                kept.append(f"  {path}: {exc.strerror}")
        self.temps.clear()
        if kept:
            listing = "\n".join(kept)
            print(
                f"zipseal: warning: could not delete temporary files. Delete them before "
                f"the next run:\n{listing}",
                file=self.warn,
            )


def create_exclusive(path: Path) -> int:
    """Create a new file with mode 0600. Never follow or reuse an existing name."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        return os.open(path, flags, 0o600)
    except FileExistsError:
        raise WriteError(f"{path}: already exists; refusing to write through it") from None
    except OSError as exc:
        raise WriteError(f"{path}: {exc.strerror}") from None
