"""Walk the inputs into an ordered list of entries (SPEC.md §6.1, §6.5, §6.8).

Every input is opened through a descriptor for its parent folder, held for the
whole run. Each entry records the (device, inode) of every component between that
root and itself, so the writer can detect a file or folder swapped after collection.
"""

import fnmatch
import os
import re
import stat
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TextIO

from zipseal.errors import InputError

DOS_MIN = datetime(1980, 1, 1, 0, 0, 0)
DOS_MAX = datetime(2107, 12, 31, 23, 59, 58)

Identity = tuple[int, int]


@dataclass(frozen=True)
class FileEntry:
    root: int  # index into Collection.roots
    relparts: tuple[str, ...]  # path from the root, as on disk
    arcname: str  # NFC, "/"-separated; directories end with "/"
    size: int
    mtime: datetime
    mode: int  # permission bits only
    is_dir: bool
    chain: tuple[Identity, ...]  # identity of each component in relparts


@dataclass
class Collection:
    roots: list[int] = field(default_factory=list)  # open directory descriptors
    entries: list[FileEntry] = field(default_factory=list)
    follow_symlinks: bool = False

    def close(self) -> None:
        for fd in self.roots:
            os.close(fd)
        self.roots.clear()

    def __enter__(self) -> "Collection":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _ident(st: os.stat_result) -> Identity:
    return (st.st_dev, st.st_ino)


def _excluded(name: str, arcpath: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        target = arcpath if "/" in pattern else name
        if fnmatch.fnmatchcase(target, pattern):
            return True
    return False


def _clamp(st: os.stat_result, arcname: str, warn: TextIO) -> datetime:
    try:
        when = datetime.fromtimestamp(st.st_mtime)
    except (OverflowError, OSError, ValueError):
        when = DOS_MIN if st.st_mtime < 0 else DOS_MAX
    if when < DOS_MIN or when > DOS_MAX:
        clamped = DOS_MIN if when < DOS_MIN else DOS_MAX
        print(
            f"zipseal: warning: {arcname}: timestamp {when:%Y-%m-%d} is outside the zip "
            f"range; stored as {clamped:%Y-%m-%d}",
            file=warn,
        )
        return clamped
    return when


class _OutputFilter:
    """Recognise this run's own output files when the output sits inside an input."""

    def __init__(self, output: Path) -> None:
        out = Path(os.path.abspath(output))
        self.name = out.name
        stem, suffix = out.stem, out.suffix
        self.part_re = re.compile(re.escape(stem) + r"-part\d+-of-\d+" + re.escape(suffix))
        self.partial_prefix = stem
        try:
            self.dir_ident: Identity | None = _ident(os.stat(out.parent))
        except OSError:
            self.dir_ident = None

    def skip(self, dir_ident: Identity, name: str) -> bool:
        if dir_ident != self.dir_ident:
            return False
        return (
            name == self.name
            or self.part_re.fullmatch(name) is not None
            or (name.startswith(self.partial_prefix) and name.endswith(".partial"))
        )


class _Walker:
    def __init__(self, excludes: list[str], follow: bool, output: Path, warn: TextIO) -> None:
        self.excludes = excludes
        self.follow = follow
        self.output = _OutputFilter(output)
        self.warn = warn
        self.collection = Collection(follow_symlinks=follow)
        self.undecodable: list[str] = []

    def _warn(self, message: str) -> None:
        print(f"zipseal: warning: {message}", file=self.warn)

    def _arcname(self, parts: tuple[str, ...], is_dir: bool) -> str | None:
        try:
            for part in parts:
                part.encode("utf-8")
        except UnicodeEncodeError:
            self.undecodable.append(os.fsencode("/".join(parts)).decode("utf-8", "replace"))
            return None
        name = unicodedata.normalize("NFC", "/".join(parts))
        return name + "/" if is_dir else name

    def _add(
        self,
        root: int,
        parts: tuple[str, ...],
        st: os.stat_result,
        chain: tuple[Identity, ...],
    ) -> None:
        is_dir = stat.S_ISDIR(st.st_mode)
        arcname = self._arcname(parts, is_dir)
        if arcname is None:
            return
        self.collection.entries.append(
            FileEntry(
                root=root,
                relparts=parts,
                arcname=arcname,
                size=0 if is_dir else st.st_size,
                mtime=_clamp(st, arcname, self.warn),
                mode=stat.S_IMODE(st.st_mode),
                is_dir=is_dir,
                chain=chain,
            )
        )

    def _classify(self, st: os.stat_result, display: str) -> str | None:
        """Return "dir", "file", or None (skipped with a warning)."""
        if stat.S_ISLNK(st.st_mode):
            self._warn(f"{display}: skipping symlink (use --follow-symlinks to follow)")
            return None
        if stat.S_ISDIR(st.st_mode):
            return "dir"
        if stat.S_ISREG(st.st_mode):
            return "file"
        self._warn(f"{display}: skipping special file (socket, FIFO or device)")
        return None

    def add_input(self, path: Path) -> None:
        absolute = Path(os.path.abspath(path))
        name = absolute.name
        if not name:
            raise InputError(f"{path}: cannot archive a filesystem root")
        try:
            parent_fd = os.open(absolute.parent, os.O_RDONLY | os.O_DIRECTORY)
        except OSError as exc:
            raise InputError(f"{path}: {exc.strerror}") from None
        root = len(self.collection.roots)
        self.collection.roots.append(parent_fd)
        try:
            st = os.stat(name, dir_fd=parent_fd, follow_symlinks=self.follow)
        except FileNotFoundError:
            raise InputError(f"{path}: no such file or folder") from None
        except OSError as exc:
            raise InputError(f"{path}: {exc.strerror}") from None
        kind = self._classify(st, str(path))
        if kind == "file":
            if not _excluded(name, name, self.excludes):
                self._add(root, (name,), st, (_ident(st),))
        elif kind == "dir":
            self._walk_dir(root, name, st)

    def _walk_dir(self, root: int, top: str, top_st: os.stat_result) -> None:
        parent_fd = self.collection.roots[root]
        chains: dict[str, tuple[Identity, ...]] = {top: (_ident(top_st),)}
        dir_stats: dict[str, os.stat_result] = {top: top_st}
        has_children: set[str] = set()
        walk = os.fwalk(top, dir_fd=parent_fd, follow_symlinks=self.follow)
        for dirpath, dirnames, filenames, dirfd in walk:
            chain = chains[dirpath]
            here = _ident(os.fstat(dirfd))
            keep_dirs: list[str] = []
            for name in sorted(dirnames + filenames):
                parts = (*dirpath.split("/"), name)
                arcpath = "/".join(parts)
                display = arcpath
                if self.output.skip(here, name):
                    continue
                if _excluded(name, arcpath, self.excludes):
                    continue
                try:
                    st = os.stat(name, dir_fd=dirfd, follow_symlinks=self.follow)
                except OSError as exc:
                    self._warn(f"{display}: skipping ({exc.strerror})")
                    continue
                kind = self._classify(st, display)
                if kind is None:
                    continue
                child_chain = (*chain, _ident(st))
                has_children.add(dirpath)
                if kind == "dir":
                    if _ident(st) in chain:
                        raise InputError(f"{display}: symlink cycle back to a parent folder")
                    chains[arcpath] = child_chain
                    dir_stats[arcpath] = st
                    keep_dirs.append(name)
                else:
                    self._add(root, parts, st, child_chain)
            dirnames[:] = [d for d in dirnames if d in keep_dirs]
        # Store folders with nothing collected under them as directory entries.
        for dirpath, chain in chains.items():
            if dirpath not in has_children:
                self._add(root, tuple(dirpath.split("/")), dir_stats[dirpath], chain)


def _check_collisions(entries: list[FileEntry]) -> None:
    """Fail on paths that would clash when extracted, including on case-insensitive disks:
    the same path twice, paths differing only in case, and a file whose name is also a
    folder on another entry's path."""
    folded: dict[str, list[FileEntry]] = {}
    for entry in entries:
        folded.setdefault(entry.arcname.casefold(), []).append(entry)
    lines = []
    for group in folded.values():
        if len(group) > 1:
            names = sorted({e.arcname for e in group})
            kind = "same path" if len(names) == 1 else "differ only in case"
            lines.append(f"  {', '.join(names)} ({kind}, {len(group)} sources)")
    files = {e.arcname.casefold(): e.arcname for e in entries if not e.is_dir}
    for entry in entries:
        parts = entry.arcname.rstrip("/").split("/")
        for depth in range(1, len(parts)):
            ancestor = "/".join(parts[:depth]).casefold()
            if ancestor in files:
                lines.append(
                    f"  {files[ancestor]}, {entry.arcname} (a file and a folder share a name)"
                )
                break
    if lines:
        raise InputError("archive path collisions:\n" + "\n".join(lines))


def collect(
    paths: list[Path],
    *,
    excludes: list[str],
    follow_symlinks: bool,
    output: Path,
    warn: TextIO | None = None,
) -> Collection:
    """Walk every input. The caller must close() the result (or use `with`)."""
    walker = _Walker(excludes, follow_symlinks, output, warn or sys.stderr)
    try:
        for path in paths:
            walker.add_input(path)
        if walker.undecodable:
            listing = "\n".join(f"  {p}" for p in walker.undecodable)
            raise InputError(f"file names that are not valid UTF-8:\n{listing}")
        walker.collection.entries.sort(key=lambda e: e.arcname)
        _check_collisions(walker.collection.entries)
    except BaseException:
        walker.collection.close()
        raise
    return walker.collection
