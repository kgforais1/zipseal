"""The desktop GUI's controller: the whole GUI with no Tk in it (plan: Desktop GUI).

`Controller` turns the window's plain values into `Options`, checks the two
password fields, generates a password on the calling (main) thread before the
worker exists, and runs one job in a daemon thread that reports back over a
`queue.Queue`. The worker never touches a widget and the view never touches the
job.

`gui_view` is the window; it is imported by `main()` below, so importing this
module (and testing the controller) needs no display.

Security rules for this pair of modules (plan, "Security rules for the GUI"):
password fields are always masked; a generated password is made on the main
thread, reaches the worker only through the `get_password` callback, is shown in
a modal only after a successful run, and is never written to the log area (the
core is called without a `password_out`, so it has nowhere to print one); the
fields are cleared after every run; nothing is persisted; and error dialogs show
`ZipsealError` messages only, with one generic line for anything unexpected.
"""

from __future__ import annotations

import io
import queue
import threading
import time
import traceback
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import NamedTuple, TextIO

from zipseal import passwords
from zipseal.errors import UsageError, ZipsealError
from zipseal.job import run_job
from zipseal.options import Options
from zipseal.output import Output
from zipseal.passwords import Password
from zipseal.progress import Progress
from zipseal.sizes import parse_size


# ── what the worker puts on the queue, as typed events ────────────────────────
class Log(NamedTuple):
    """One line for the log area: the core's warnings and its final report."""

    line: str


class ProgressUpdate(NamedTuple):
    """One of the core's `Progress` events, for the status line and the bar."""

    phase: str  # "started", "bytes", "verifying" or "verified"
    number: int  # the part, or 0 when the phase has no part number
    value: int  # bytes written, or the verified part's size


class Error(NamedTuple):
    """A `ZipsealError` message, or the one generic line for anything unexpected."""

    message: str


class Done(NamedTuple):
    """The worker finished: the run either succeeded or already reported why not."""


Event = Log | ProgressUpdate | Error | Done

UNEXPECTED = "zipseal stopped: an unexpected error, and no archive was written"


@dataclass(frozen=True)
class JobSpec:
    """What the window lets the user set, as plain values (plan: Screen).

    `max_size` is in bytes, `level` is a deflate level, and `excludes` is text
    with one glob per line, like the CLI's repeated `--exclude`.
    """

    paths: list[Path]
    output: Path
    max_size: int | None
    level: int
    excludes: str = ""
    follow_symlinks: bool = False
    hide_names: bool = False
    force: bool = False
    dry_run: bool = False


class _LogSink(io.StringIO):
    """A warning sink that turns worker output into queue events and keeps no text.

    It is a `StringIO` because the core's sinks are typed as text streams. Each
    complete line becomes a `Log` event for the view to append, and is not kept,
    so nothing the worker writes accumulates here.
    """

    def __init__(self, events: queue.Queue[Event]) -> None:
        super().__init__()
        self._events = events
        self._partial = ""

    def write(self, text: str) -> int:
        self._partial += text
        while "\n" in self._partial:
            line, _, self._partial = self._partial.partition("\n")
            if line:
                self._events.put(Log(line))
        return len(text)

    def flush(self) -> None:
        """Nothing is buffered on disk, so `print(..., flush=True)` changes nothing."""


BYTES_INTERVAL = 0.1  # seconds between byte-count events, so the queue stays short


class _QueueProgress:
    """A `Progress` that puts events on the queue. It runs in the worker thread, so
    the queue is the only thing it touches.

    Byte counts are running totals, so each one replaces the last. At most one is
    queued per `BYTES_INTERVAL`, which bounds the queue however fast the disk is.
    """

    def __init__(self, events: queue.Queue[Event]) -> None:
        self._events = events
        self._last_bytes = float("-inf")

    def part_started(self, number: int) -> None:
        self._events.put(ProgressUpdate("started", number, 0))
        self._last_bytes = float("-inf")

    def bytes_written(self, written: int) -> None:
        now = time.monotonic()
        if now - self._last_bytes >= BYTES_INTERVAL:
            self._last_bytes = now
            self._events.put(ProgressUpdate("bytes", 0, written))

    def verifying(self, parts: int) -> None:
        self._events.put(ProgressUpdate("verifying", 0, parts))

    def part_verified(self, number: int, size: int) -> None:
        self._events.put(ProgressUpdate("verified", number, size))


CUSTOM_SIZE = "Custom…"
SIZE_PRESETS = (
    "no limit",
    "10 MB",
    "20 MB",
    "100 MB",
    "500 MB",
    "1 GB",
    "5 GB",
    "10 GB",
    "20 GB",
    CUSTOM_SIZE,
)


def parse_max_size(text: str, custom_mb: str = "") -> int | None:
    """Turn the size choice into a cap in bytes, or None for no limit.

    `CUSTOM_SIZE` takes its value from `custom_mb`, a plain number of
    megabytes (1 MB = 1,000,000 bytes, as in the CLI).
    """
    stripped = text.strip()
    if stripped.lower() in ("", "no limit"):
        return None
    if stripped == CUSTOM_SIZE:
        return _parse_custom_mb(custom_mb)
    return parse_size(stripped)


def _parse_custom_mb(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        raise UsageError("enter the custom part size in MB")
    try:
        megabytes = Decimal(stripped)
    except InvalidOperation:
        raise UsageError(
            f"the custom part size must be a number of MB, such as 25, not {stripped!r}"
        ) from None
    if not megabytes.is_finite():
        raise UsageError(f"the custom part size must be a number of MB, not {stripped!r}")
    if megabytes <= 0:
        raise UsageError(f"the custom part size must be greater than zero, not {stripped!r}")
    size = megabytes * 1_000_000
    if size != size.to_integral_value():
        raise UsageError(f"the custom part size {stripped!r} MB is not a whole number of bytes")
    return int(size)


def parse_level(text: str) -> int:
    """Turn the level box into a deflate level."""
    try:
        level = int(text.strip())
    except ValueError:
        raise UsageError(
            f"the compression level must be a whole number from 0 to 9, not {text.strip()!r}"
        ) from None
    if not 0 <= level <= 9:
        raise UsageError(f"the compression level must be from 0 to 9, not {level}")
    return level


def build_options(spec: JobSpec) -> Options:
    """Turn a `JobSpec` into `Options`, as `cli.parse_args` does for the CLI.

    Raises `UsageError` for anything the window should report before a thread
    starts. The screen has no manifest or verify switch, so those stay off, and
    `default_excludes` stays on: the junk-file globs are always skipped.
    """
    if not spec.paths:
        raise UsageError("add at least one file or folder")
    if not spec.output.name:
        # An empty output box arrives as `Path("")`, which is `Path(".")`.
        raise UsageError("choose an output name")
    excludes = [line.strip() for line in spec.excludes.splitlines() if line.strip()]
    return Options(
        paths=list(spec.paths),
        output=spec.output,
        max_size=spec.max_size,
        level=spec.level,
        excludes=excludes,
        default_excludes=True,
        follow_symlinks=spec.follow_symlinks,
        hide_names=spec.hide_names,
        order="path",
        no_verify=False,
        force=spec.force,
        dry_run=spec.dry_run,
    )


def existing_outputs(options: Options) -> list[Path]:
    """The names this run would write over (SPEC.md §6.5), for the overwrite question.

    A folder that cannot be listed is not reported here; the job itself reports it,
    with the message the CLI would show.
    """
    try:
        return Output(options.output, force=False).existing()
    except ZipsealError:
        return []


class Controller:
    """One window's model: it runs a job and reports over a queue.

    This is plain Python, so it is testable without a display. The view reads its
    widgets into a `JobSpec`, calls `start`, and drains `poll()` from `after()`.
    The worker thread only puts events on the queue.
    """

    def __init__(self) -> None:
        self.events: queue.Queue[Event] = queue.Queue()
        self._generated: Password | None = None

    # ── main thread ───────────────────────────────────────────────────────────

    def start(
        self,
        spec: JobSpec,
        *,
        generate: bool = False,
        password: str = "",
        confirm: str = "",
    ) -> None:
        """Validate, then run `spec` in a daemon thread.

        Raises `UsageError` for anything the window should show without starting a
        thread: a malformed option, or two passwords that do not match. Password
        length and content stay the core's check, not this one's.
        """
        options = build_options(spec)
        secret: Password | None = None
        if generate and not spec.dry_run:
            # Made here, on the main thread, before the worker exists (plan).
            self._generated = secret = passwords.generate()
        elif not spec.dry_run and not generate:
            if password != confirm:
                raise UsageError("the two passwords do not match")
            secret = Password(password)
        # A dry run never asks for a password (SPEC.md §6.6), so there is nothing
        # to hand over.
        holder = secret if secret is not None else Password("")

        progress = _QueueProgress(self.events)
        log = _LogSink(self.events)
        threading.Thread(
            target=self._work,
            args=(options, holder, progress, log),
            daemon=True,
        ).start()

    def poll(self) -> list[Event]:
        """Everything queued since the last call, oldest first."""
        events: list[Event] = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                return events

    def take_generated_password(self) -> Password | None:
        """Hand the generated password to the caller exactly once.

        Only call this after a `Done` event, on the main thread: the worker reads
        nothing else from the controller, and a failed run has already cleared it.
        """
        password, self._generated = self._generated, None
        return password

    def clear_password(self) -> None:
        """Forget any generated password: the run failed, or it is over."""
        self._generated = None

    # ── worker thread ─────────────────────────────────────────────────────────

    def _work(
        self,
        options: Options,
        password: Password,
        progress: Progress,
        log: TextIO,
    ) -> None:
        try:
            # No `password_out`: the generated password is shown in a modal, never
            # in the log area.
            run_job(options, lambda _: password, progress=progress, warn=log, out=log)
        except ZipsealError as exc:
            self.events.put(Error(str(exc)))
        except Exception:
            # A bug. The plan shows no traceback, so the view only gets the generic
            # line; the traceback goes to the console for a bug report.
            traceback.print_exc()
            self.events.put(Error(UNEXPECTED))
        else:
            self.events.put(Done())
            # A successful run keeps it: the view takes it for the modal.
            return
        # A failed run never shows a password, and nothing can be taking it while
        # this happens, because a take only ever follows a `Done`.
        self.clear_password()


def main() -> int:
    """Open the window: the `zipseal-gui` script entry point."""
    from zipseal.gui_view import run  # Tk is imported there, not here (plan: threading)

    return run()


__all__ = [
    "CUSTOM_SIZE",
    "SIZE_PRESETS",
    "Controller",
    "Done",
    "Error",
    "Event",
    "JobSpec",
    "Log",
    "ProgressUpdate",
    "build_options",
    "existing_outputs",
    "main",
    "parse_level",
    "parse_max_size",
]
