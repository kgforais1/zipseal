"""The GUI controller, with no display and no widgets (plan: controller tests).

Everything here drives `zipseal.gui.Controller` on the calling thread, so it runs
wherever pytest does. The worker is joined through the queue: `run_to_completion`
waits for the next event with a timeout and fails if the worker never reports
finishing, so nothing depends on a sleep. The window itself (`zipseal.gui_view`)
is Tk, and any test that needs a real display carries the `gui` marker, which
`addopts` deselects.
"""

import os
import queue
import threading
import time
from pathlib import Path

import pytest
from helpers import leftovers, make_tree

from zipseal import gui, passwords, pipeline
from zipseal.errors import UsageError, WriteError
from zipseal.gui import (
    CUSTOM_SIZE,
    SIZE_PRESETS,
    Controller,
    Done,
    Error,
    JobSpec,
    Log,
    ProgressUpdate,
    Stopped,
    build_options,
    existing_outputs,
    parse_level,
    parse_max_size,
)
from zipseal.options import Options
from zipseal.passwords import Password

PASSWORD = "test-password"
GENERATED = "test-generated-password"
TIMEOUT = 60.0


def make_source(tmp_path: Path) -> Path:
    """A small folder with one incompressible file, so the parts are real."""
    source = tmp_path / "in"
    make_tree(source, {"a.txt": "hello\n", "b.bin": os.urandom(4096), ".DS_Store": "junk"})
    return source


def spec(tmp_path: Path, **overrides: object) -> JobSpec:
    """A complete, valid `JobSpec`, with anything the test wants changed."""
    output = tmp_path / "out" / "b.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    values: dict[str, object] = {
        "paths": [make_source(tmp_path)],
        "output": output,
        "max_size": None,
        "level": 6,
        "excludes": "",
    }
    values.update(overrides)
    return JobSpec(**values)  # type: ignore[arg-type]


def start(controller: Controller, job: JobSpec, **kwargs: object) -> list[object]:
    """Start the worker and wait for it to report finishing, on the queue.

    Returns every event the worker produced, oldest first.
    """
    controller.start(job, **kwargs)  # type: ignore[arg-type]
    return run_to_completion(controller)


def run_to_completion(controller: Controller, timeout: float = TIMEOUT) -> list[object]:
    """Drain the queue until the worker reports it finished."""
    events: list[object] = []
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        assert remaining > 0, "the worker never reported finishing"
        try:
            events.append(controller.events.get(timeout=remaining))
        except queue.Empty:
            pytest.fail("the worker never reported finishing")
        if isinstance(events[-1], (Done, Error, Stopped)):
            return events


def log_lines(events: list[object]) -> list[str]:
    return [event.line for event in events if isinstance(event, Log)]


def error_events(events: list[object]) -> list[Error]:
    return [event for event in events if isinstance(event, Error)]


def messages(events: list[object]) -> list[str]:
    return [event.message for event in events if isinstance(event, Error)]


def progress(events: list[object]) -> list[ProgressUpdate]:
    return [event for event in events if isinstance(event, ProgressUpdate)]


def options_for(tmp_path: Path, **overrides: object) -> Options:
    return build_options(spec(tmp_path, **overrides))


def force_failure(monkeypatch: pytest.MonkeyPatch, message: str = "forced failure") -> None:
    """Make verification fail, so the job stops after its parts are on disk."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise WriteError(message)

    monkeypatch.setattr(pipeline, "verify_part", refuse)


# ── build_options ─────────────────────────────────────────────────────────────


def test_build_options_maps_every_field(tmp_path: Path) -> None:
    options = build_options(
        spec(
            tmp_path,
            max_size=25_000_000,
            level=0,
            excludes="*.tmp\n\n  *.log  \n",
            follow_symlinks=True,
            hide_names=True,
            force=True,
            dry_run=True,
        )
    )
    assert options.paths == [tmp_path / "in"]
    assert options.output == tmp_path / "out" / "b.zip"
    assert options.max_size == 25_000_000
    assert options.level == 0
    assert options.excludes == ["*.tmp", "*.log"]
    assert options.follow_symlinks is True
    assert options.hide_names is True
    assert options.force is True
    assert options.dry_run is True
    # The defaults the window does not offer.
    assert options.default_excludes is True
    assert options.order == "path"
    assert options.manifest is False
    assert options.no_verify is False
    assert options.all_excludes() == [".DS_Store", "._*", "Thumbs.db", "*.tmp", "*.log"]


def test_build_options_defaults_the_unset_fields(tmp_path: Path) -> None:
    options = options_for(tmp_path)
    assert options.max_size is None
    assert options.level == 6
    assert options.excludes == []
    assert options.all_excludes() == [".DS_Store", "._*", "Thumbs.db"]
    assert options.follow_symlinks is False
    assert options.hide_names is False
    assert options.force is False
    assert options.dry_run is False


def test_build_options_needs_a_path(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="add at least one file or folder"):
        options_for(tmp_path, paths=[])


@pytest.mark.parametrize("output", [Path(""), Path(".")])
def test_build_options_needs_an_output_name(tmp_path: Path, output: Path) -> None:
    # An empty box reaches here as `Path("")`, which is `Path(".")`.
    with pytest.raises(UsageError, match="choose an output name"):
        options_for(tmp_path, output=output)


# ── the option boxes ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", None),
        ("   ", None),
        ("no limit", None),
        ("No Limit", None),
        ("10 MB", 10_000_000),
        ("300 KB", 300_000),
        ("1048576", 1_048_576),
    ],
)
def test_parse_max_size(text: str, expected: int | None) -> None:
    assert parse_max_size(text) == expected


def test_parse_max_size_rejects_nonsense() -> None:
    with pytest.raises(UsageError, match="invalid size"):
        parse_max_size("twenty megabytes")


def test_size_presets_parse_to_decimal_caps() -> None:
    caps = [parse_max_size(choice) for choice in SIZE_PRESETS if choice != CUSTOM_SIZE]
    assert caps == [
        None,
        10_000_000,
        20_000_000,
        100_000_000,
        500_000_000,
        1_000_000_000,
        5_000_000_000,
        10_000_000_000,
        20_000_000_000,
    ]


@pytest.mark.parametrize(
    ("custom", "expected"),
    [("25", 25_000_000), (" 7.5 ", 7_500_000), ("1000", 1_000_000_000)],
)
def test_custom_size_is_megabytes(custom: str, expected: int) -> None:
    assert parse_max_size(CUSTOM_SIZE, custom) == expected


@pytest.mark.parametrize(
    ("custom", "message"),
    [
        ("", "enter the custom part size in MB"),
        ("5 GB", "must be a number of MB"),
        ("abc", "must be a number of MB"),
        ("Infinity", "must be a number of MB"),
        ("0", "must be greater than zero"),
        ("-3", "must be greater than zero"),
        ("0.0000001", "not a whole number of bytes"),
    ],
)
def test_custom_size_rejects_bad_input(custom: str, message: str) -> None:
    with pytest.raises(UsageError, match=message):
        parse_max_size(CUSTOM_SIZE, custom)


def test_custom_box_is_ignored_unless_custom_is_chosen() -> None:
    assert parse_max_size("20 MB", "not a number") == 20_000_000


def test_parse_level() -> None:
    assert parse_level(" 6 ") == 6
    assert parse_level("0") == 0
    assert parse_level("9") == 9


@pytest.mark.parametrize("text", ["eleven", "six", "", "6.5"])
def test_parse_level_rejects_nonsense(text: str) -> None:
    with pytest.raises(UsageError, match="whole number from 0 to 9"):
        parse_level(text)


@pytest.mark.parametrize("text", ["10", "-1"])
def test_parse_level_rejects_out_of_range(text: str) -> None:
    with pytest.raises(UsageError, match="from 0 to 9"):
        parse_level(text)


# ── the password fields ───────────────────────────────────────────────────────


def test_mismatched_passwords_raise_before_any_thread_starts(tmp_path: Path) -> None:
    controller = Controller()
    before = threading.active_count()
    with pytest.raises(UsageError, match="the two passwords do not match"):
        controller.start(spec(tmp_path), password="test-password-one", confirm="test-password-two")
    assert threading.active_count() == before
    assert controller.poll() == []
    assert controller.take_generated_password() is None
    assert not (tmp_path / "out" / "b.zip").exists()


def test_a_dry_run_asks_for_no_password(tmp_path: Path) -> None:
    controller = Controller()
    events = start(controller, spec(tmp_path, dry_run=True))
    assert isinstance(events[-1], Done)
    assert error_events(events) == []
    assert any("entries," in line for line in log_lines(events))
    assert not (tmp_path / "out" / "b.zip").exists()
    assert controller.take_generated_password() is None


def test_a_dry_run_with_generate_makes_no_password(tmp_path: Path) -> None:
    """A dry run writes no archive, so there is no password to show."""
    controller = Controller()
    events = start(controller, spec(tmp_path, dry_run=True), generate=True)
    assert isinstance(events[-1], Done)
    assert controller.take_generated_password() is None


def test_byte_events_are_throttled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Running totals replace each other, so only one per interval is queued."""
    clock = iter([0.0, 0.01, 0.02, 0.5, 0.51])
    monkeypatch.setattr(gui.time, "monotonic", lambda: next(clock))
    events: queue.Queue[object] = queue.Queue()
    progress = gui._QueueProgress(events, threading.Event())  # type: ignore[arg-type]
    for written in (10, 20, 30, 40, 50):
        progress.bytes_written(written)
    queued = [events.get_nowait() for _ in range(events.qsize())]
    assert [e.value for e in queued] == [10, 40]  # type: ignore[attr-defined]


def test_an_empty_password_is_rejected_by_the_core(tmp_path: Path) -> None:
    controller = Controller()
    events = start(controller, spec(tmp_path), password="", confirm="")
    assert messages(events) == ["the password is empty"]
    assert not isinstance(events[-1], Done)
    assert not (tmp_path / "out" / "b.zip").exists()
    assert controller.take_generated_password() is None


# ── the generated password ────────────────────────────────────────────────────


def test_a_generated_password_is_made_on_the_calling_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    threads: list[threading.Thread] = []

    def fake_generate() -> Password:
        threads.append(threading.current_thread())
        return Password(GENERATED, generated=True)

    monkeypatch.setattr(passwords, "generate", fake_generate)
    controller = Controller()
    events = start(controller, spec(tmp_path), generate=True)

    # Made here, before the worker exists: the worker only gets a closure back.
    assert threads == [threading.main_thread()]
    assert isinstance(events[-1], Done)
    assert GENERATED not in " ".join(str(event) for event in events)
    assert all(GENERATED not in line for line in log_lines(events))
    assert (tmp_path / "out" / "b.zip").exists()
    # The run reports the same way the CLI does, through the warn sink.
    assert any(line.startswith("zipseal: wrote 1 part (") for line in log_lines(events))
    # The controller holds it until the view asks, exactly once.
    taken = controller.take_generated_password()
    assert taken is not None
    assert taken.value == GENERATED
    assert controller.take_generated_password() is None


def test_progress_events_reach_the_view(tmp_path: Path) -> None:
    controller = Controller()
    events = start(controller, spec(tmp_path), password=PASSWORD, confirm=PASSWORD)
    assert [(e.phase, e.number, e.value) for e in progress(events) if e.phase == "started"] == [
        ("started", 1, 0)
    ]
    size = (tmp_path / "out" / "b.zip").stat().st_size
    written = [e.value for e in progress(events) if e.phase == "bytes"]
    assert written and written == sorted(written)
    assert 0 < written[0] and written[-1] <= size
    verified = [e for e in progress(events) if e.phase == "verified"]
    assert [(e.number, e.value) for e in verified] == [
        (1, (tmp_path / "out" / "b.zip").stat().st_size)
    ]
    # The .partial notice comes first, then every progress event, then the finish.
    kinds = [type(e).__name__ for e in events]
    assert kinds[:2] == ["Log", "ProgressUpdate"] and kinds[-1] == "Done"
    first = events[0]
    assert isinstance(first, Log) and "Do not rename" in first.line


def test_cancel_mid_write_stops_and_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = Controller()
    original = gui._QueueProgress.bytes_written  # pyright: ignore[reportPrivateUsage]

    def cancel_then_count(self: gui._QueueProgress, written: int) -> None:  # pyright: ignore[reportPrivateUsage]
        controller.cancel()  # pressed while the first chunk is on disk
        original(self, written)

    monkeypatch.setattr(gui._QueueProgress, "bytes_written", cancel_then_count)  # pyright: ignore[reportPrivateUsage]
    events = start(controller, spec(tmp_path), generate=True)
    last = events[-1]
    assert isinstance(last, Stopped) and last.message == "cancelled: no archive was written"
    assert not error_events(events)
    assert os.listdir(tmp_path / "out") == []
    assert controller.take_generated_password() is None


def test_an_old_cancel_does_not_stop_the_next_run(tmp_path: Path) -> None:
    controller = Controller()
    controller.cancel()
    events = start(controller, spec(tmp_path), password=PASSWORD, confirm=PASSWORD)
    assert isinstance(events[-1], Done)
    assert (tmp_path / "out" / "b.zip").exists()


def test_a_generated_password_is_cleared_after_a_failed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    force_failure(monkeypatch)
    controller = Controller()
    events = start(controller, spec(tmp_path), generate=True)
    assert messages(events) == ["forced failure"]
    assert not isinstance(events[-1], Done)
    assert not (tmp_path / "out" / "b.zip").exists()
    assert controller.take_generated_password() is None


# ── a failed run ──────────────────────────────────────────────────────────────


def test_a_failed_run_leaves_no_partial_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    force_failure(monkeypatch)
    controller = Controller()
    events = start(controller, spec(tmp_path), password=PASSWORD, confirm=PASSWORD)
    assert messages(events) == ["forced failure"]
    assert not isinstance(events[-1], Done)
    assert leftovers(tmp_path / "out") == []
    assert not any(path.is_file() for path in (tmp_path / "out").iterdir())


def test_the_worker_is_a_daemon_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The window can close while a job is still running."""
    made: list[threading.Thread] = []
    real_thread = threading.Thread

    def spy(*args: object, **kwargs: object) -> threading.Thread:
        thread = real_thread(*args, **kwargs)  # type: ignore[arg-type]
        made.append(thread)
        return thread

    monkeypatch.setattr(threading, "Thread", spy)
    controller = Controller()
    assert isinstance(start(controller, spec(tmp_path, dry_run=True))[-1], Done)
    assert len(made) == 1
    assert made[0].daemon is True


# ── the overwrite question ────────────────────────────────────────────────────


def test_existing_outputs_finds_the_names_a_run_would_replace(tmp_path: Path) -> None:
    out = tmp_path / "out"
    options = options_for(tmp_path)
    assert existing_outputs(options) == []

    (out / "b.zip").write_text("old single")
    assert existing_outputs(options) == [out / "b.zip"]

    (out / "b-volume01-of-02.zip").write_text("old part")
    assert existing_outputs(options) == [out / "b-volume01-of-02.zip", out / "b.zip"]

    (out / "unrelated.zip").write_text("keep me")
    (out / "b.zip.partial").write_text("keep me too")
    assert existing_outputs(options) == [out / "b-volume01-of-02.zip", out / "b.zip"]


def test_existing_outputs_of_a_missing_folder_is_empty(tmp_path: Path) -> None:
    assert existing_outputs(options_for(tmp_path)) == []
