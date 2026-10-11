"""Progress events: order, byte totals, and what they never carry (GUI plan chunk 2)."""

import io
import os
from pathlib import Path

import pytest
from helpers import PASSWORD, args_for, collect_for, make_tree

from zipseal import cli
from zipseal.errors import EXIT_OK
from zipseal.job import run_job
from zipseal.options import Options
from zipseal.passwords import Password
from zipseal.pipeline import write_archive
from zipseal.progress import Progress
from zipseal.write import PartResult

Event = tuple[str, int, int]

SECRET = "test-secret-password"
CONTENTS = "PLAINTEXT-SECRET-CONTENTS"


class Recorder:
    """A `Progress` that keeps every event, in order."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.part = 0

    def part_started(self, number: int) -> None:
        self.part = number
        self.events.append(("started", number, 0))

    def bytes_written(self, written: int) -> None:
        self.events.append(("bytes", self.part, written))

    def verifying(self, parts: int) -> None:
        self.events.append(("verifying", 0, parts))

    def part_verified(self, number: int, size: int) -> None:
        self.events.append(("verified", number, size))

    def of(self, kind: str) -> list[Event]:
        return [e for e in self.events if e[0] == kind]

    def numbers(self, kind: str) -> list[int]:
        return [number for _, number, _ in self.of(kind)]


def make_src(tmp_path: Path, files: int = 6, size: int = 150_000) -> Path:
    """Incompressible files, so a size cap really does split the archive into parts."""
    src = tmp_path / "src"
    for i in range(files):
        make_tree(src, {f"file-{i:02d}.bin": os.urandom(size)})
    return src


def archive_with(
    tmp_path: Path, *extra: str, name: str = "out"
) -> tuple[list[PartResult], Recorder]:
    """One archive per call, so a test can compare two runs in the same tmp_path."""
    destination = tmp_path / name
    destination.mkdir(exist_ok=True)
    options = args_for([make_src(tmp_path)], destination / "o.zip", *extra)
    rec = Recorder()
    with collect_for(options) as c:
        results = write_archive(options, c, lambda _: Password(PASSWORD), progress=rec)
    return results, rec


def test_recorder_is_a_progress() -> None:
    assert isinstance(Recorder(), Progress)


def test_one_part_reports_one_lifecycle(tmp_path: Path) -> None:
    results, rec = archive_with(tmp_path)
    assert len(results) == 1
    assert [kind for kind, _, _ in rec.events[:1]] == ["started"]
    assert [kind for kind, _, _ in rec.events[-1:]] == ["verified"]
    assert rec.numbers("started") == [1]
    assert rec.of("verified") == [("verified", 1, results[0].size)]
    assert rec.of("bytes"), "the chunk loop reports at least once"


def test_bytes_grow_and_end_at_the_part_size(tmp_path: Path) -> None:
    results, rec = archive_with(tmp_path, "--max-size", "400KB")
    assert len(results) > 1
    seen: dict[int, int] = {}
    for kind, number, value in rec.events:
        if kind == "started":
            seen[number] = 0
        elif kind == "bytes":
            assert value > seen[number], "byte counts only grow"
            seen[number] = value
        elif kind == "verifying":
            assert value == len(results)
        else:
            assert kind == "verified"
            assert value == seen[number] == results[number - 1].size
    assert seen == {n: r.size for n, r in enumerate(results, 1)}


def test_parts_are_written_before_any_is_verified(tmp_path: Path) -> None:
    results, rec = archive_with(tmp_path, "--max-size", "400KB")
    assert rec.numbers("started") == list(range(1, len(results) + 1))
    assert rec.numbers("verified") == rec.numbers("started")
    kinds = [kind for kind, _, _ in rec.events]
    first_check = kinds.index("verifying")
    assert "started" not in kinds[first_check:]
    assert kinds[first_check + 1 :].count("verified") == len(results)
    assert ("verifying", 0, len(results)) in rec.events


def test_planned_parts_report_the_same_shape(tmp_path: Path) -> None:
    """--order size plans the parts upfront; the events do not change shape."""
    streamed, streamed_rec = archive_with(tmp_path, "--max-size", "400KB", name="streamed")
    planned, planned_rec = archive_with(
        tmp_path, "--max-size", "400KB", "--order", "size", name="planned"
    )
    assert len(planned) == len(streamed)
    assert planned_rec.numbers("started") == streamed_rec.numbers("started")
    assert planned_rec.numbers("verified") == streamed_rec.numbers("verified")


def test_hide_names_counts_the_encrypted_part(tmp_path: Path) -> None:
    """With --hide-names the bytes on disk are the outer entry, teed from the inner zip."""
    results, rec = archive_with(tmp_path, "--max-size", "400KB", "--hide-names")
    assert len(results) > 1
    last: dict[int, int] = {}
    for _, number, value in rec.of("bytes"):
        last[number] = value
    assert last == {n: r.size for n, r in enumerate(results, 1)}


def test_no_verify_still_reports_finished_parts(tmp_path: Path) -> None:
    """Under --no-verify nothing is decrypted, but every part is still reported."""
    results, rec = archive_with(tmp_path, "--max-size", "400KB", "--no-verify")
    assert len(results) > 1
    assert rec.numbers("verified") == list(range(1, len(results) + 1))
    assert [(n, v) for _, n, v in rec.of("verified")] == [
        (n, r.size) for n, r in enumerate(results, 1)
    ]


def test_events_carry_no_secrets(tmp_path: Path) -> None:
    """Event payloads are part numbers and byte counts, and nothing else."""
    src = tmp_path / "src"
    make_tree(src, {f"secret-{i}.txt": CONTENTS for i in range(3)})
    options = Options(paths=[src], output=tmp_path / "out.zip")
    rec = Recorder()
    with collect_for(options) as c:
        write_archive(options, c, lambda _: Password(SECRET), progress=rec)
    payload = " ".join(str(e) for e in rec.events)
    for secret in (SECRET, CONTENTS, "secret", str(tmp_path)):
        assert secret not in payload


def test_run_job_forwards_progress(tmp_path: Path) -> None:
    src = tmp_path / "src"
    make_tree(src, {"a.txt": "hello\n", "b.txt": "world\n"})
    (tmp_path / "out").mkdir()
    rec = Recorder()
    options = Options(paths=[src], output=tmp_path / "out/b.zip")
    assert run_job(options, lambda _: Password(PASSWORD), progress=rec) == EXIT_OK
    kinds = [kind for kind, _, _ in rec.events]
    assert kinds[0] == "started" and kinds[-2:] == ["verifying", "verified"]
    assert set(kinds[1:-2]) == {"bytes"}
    assert rec.of("verified")[0][2] == (tmp_path / "out/b.zip").stat().st_size
    assert (tmp_path / "out/b.zip").exists()


def test_dry_run_reports_no_progress(tmp_path: Path) -> None:
    src = tmp_path / "src"
    make_tree(src, {"a.txt": "hello\n"})
    rec = Recorder()
    options = Options(paths=[src], output=tmp_path / "out.zip", dry_run=True)
    assert run_job(options, lambda _: Password(PASSWORD), progress=rec) == EXIT_OK
    assert rec.events == []
    assert not (tmp_path / "out.zip").exists()


def test_tty_progress_lines() -> None:
    out = io.StringIO()
    progress = cli._TtyProgress(out)
    progress.part_started(1)
    progress.bytes_written(64)
    progress.part_started(2)
    progress.bytes_written(64)
    progress.verifying(2)
    progress.part_verified(1, 100)
    progress.part_verified(2, 200)
    assert out.getvalue() == (
        "zipseal: writing part 1 ...\n"
        "zipseal: writing part 2 ...\n"
        "zipseal: verifying 2 part(s) ...\n"
    )


def test_tty_progress_announces_verification_before_it_runs() -> None:
    out = io.StringIO()
    progress = cli._TtyProgress(out)
    progress.part_started(1)
    progress.verifying(1)
    assert out.getvalue() == "zipseal: writing part 1 ...\nzipseal: verifying 1 part(s) ...\n"


class _FakeTty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_cli_prints_progress_only_on_a_tty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = make_src(tmp_path, files=6, size=150_000)
    out = tmp_path / "out"
    out.mkdir()
    argv = [
        str(src),
        "-o",
        str(out / "b.zip"),
        "--max-size",
        "400KB",
        "--password-env",
        "ZS_PW",
    ]
    monkeypatch.setenv("ZS_PW", PASSWORD)

    tty = _FakeTty()
    monkeypatch.setattr(cli.sys, "stderr", tty)
    assert cli.main(argv) == EXIT_OK
    lines = tty.getvalue().splitlines()
    writing = [line for line in lines if line.startswith("zipseal: writing part")]
    assert writing == [f"zipseal: writing part {n} ..." for n in range(1, len(writing) + 1)]
    assert f"zipseal: verifying {len(writing)} part(s) ..." in lines
    assert f"zipseal: wrote {len(writing)} parts" in lines[-1]

    quiet = io.StringIO()
    monkeypatch.setattr(cli.sys, "stderr", quiet)
    assert cli.main([*argv, "--force"]) == EXIT_OK
    assert "writing part" not in quiet.getvalue()
    assert "verifying" not in quiet.getvalue()
    assert "zipseal: wrote" in quiet.getvalue()
