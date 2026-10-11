"""Progress events for one archive job (dev-docs/plans/2026-10-10-gui.md).

The CLI implements this protocol with its TTY progress lines; the GUI will
implement it with a progress bar, fed from the worker thread through a queue
polled with `after()`. Front ends never call these methods themselves.

The core invokes them in order, from the one thread that runs the job, and only
while work is happening: a part is announced before it is written, its bytes are
counted as they land, and it is reported done after its post-write check. Events
carry part numbers and byte counts, never a password, a file name, a path or
file contents.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class Progress(Protocol):
    """What a front end hears while one archive job runs.

    Exactly one part is being written at a time, so a `bytes_written` count
    belongs to the part that `part_started` announced last.
    """

    def part_started(self, number: int) -> None:
        """Part `number` (1-based) is about to be written to a `.partial` file."""
        ...

    def bytes_written(self, written: int) -> None:
        """The part in progress now holds `written` bytes on disk.

        Called once per chunk as it is written, so the count only grows and its
        last value for a part is that part's final size.
        """
        ...

    def verifying(self, parts: int) -> None:
        """Every part is written, and decrypting `parts` parts is about to start.

        Not called for a `no_verify` run.
        """
        ...

    def part_verified(self, number: int, size: int) -> None:
        """Part `number` passed its post-write check, and `size` is its size on disk.

        The check is decryption and structural verification, or only the size cap
        check when the run was started with `no_verify`.
        """
        ...
