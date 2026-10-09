"""Exception types and the exit codes they map to (SPEC.md §4).

Messages may name files. They must never contain a password or file contents.
"""

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_INPUT = 2
EXIT_WRITE = 3
EXIT_INTERRUPT = 130


class ZipsealError(Exception):
    exit_code = EXIT_WRITE


class UsageError(ZipsealError):
    exit_code = EXIT_USAGE


class InputError(ZipsealError):
    exit_code = EXIT_INPUT


class WriteError(ZipsealError):
    exit_code = EXIT_WRITE


class VerifyError(ZipsealError):
    exit_code = EXIT_WRITE
