"""The window icon ships inside the package and is set when Tk can read SVG.

A Tk that cannot read SVG falls back to the sibling PNG; a window that gets no
icon at all still launches. The package checks import no Tk, so they run on a
Python without it. The window checks import Tk inside each test and carry the
`gui` marker.
"""

import struct
import subprocess
import zipfile
import zlib
from pathlib import Path

import pytest

from zipseal.gui import ICON

REPO = Path(__file__).resolve().parent.parent


def _write_png(path: Path, width: int, height: int) -> None:
    """Write a small opaque RGBA PNG, so a fallback load is a real image."""
    raw = b"".join(b"\x00" + b"\x00\x00\x00\xff" * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = struct.pack(">I", len(data)) + tag + data
        return body + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def test_icon_is_an_svg_next_to_the_module() -> None:
    text = ICON.read_text()
    assert text.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert "<script" not in text


def test_icon_is_in_the_wheel(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path), str(REPO)],
        capture_output=True,
        timeout=120,
        check=True,
    )
    (wheel,) = tmp_path.glob("zipseal-*.whl")
    assert "zipseal/icon.svg" in zipfile.ZipFile(wheel).namelist()


@pytest.mark.gui
def test_set_icon_gives_the_window_the_image(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("tkinter")
    import tkinter as tk

    from zipseal import gui_view

    root = tk.Tk()
    try:
        if tk.TkVersion < 9:
            pytest.skip("Tk 8.x cannot read SVG")
        calls: list[tuple[bool, tk.PhotoImage]] = []
        real = root.iconphoto

        def spy(default: bool, image: tk.PhotoImage) -> None:
            calls.append((default, image))
            real(default, image)

        monkeypatch.setattr(root, "iconphoto", spy)
        assert gui_view.set_icon(root)
        assert len(calls) == 1
        default, image = calls[0]
        assert default is True
        assert isinstance(image, tk.PhotoImage)
        assert image.height() == 256
    finally:
        root.destroy()


@pytest.mark.gui
def test_png_is_the_icon_when_svg_is_unreadable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("tkinter")
    import tkinter as tk

    from zipseal import gui_view

    svg = tmp_path / "icon.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    png = tmp_path / "icon.png"
    _write_png(png, 1, 1)
    monkeypatch.setattr(gui_view, "ICON", svg)

    root = tk.Tk()
    try:
        fallback = tk.PhotoImage(master=root, file=str(png))

        def photo_image(master: tk.Misc, file: str, format: str | None = None) -> tk.PhotoImage:
            if format is not None and format.startswith("svg"):
                raise tk.TclError('image format "svg" is not supported')
            assert file == str(png)
            return fallback

        monkeypatch.setattr(gui_view.tk, "PhotoImage", photo_image)
        calls: list[tuple[bool, tk.PhotoImage]] = []
        real = root.iconphoto

        def spy(default: bool, icon: tk.PhotoImage) -> None:
            calls.append((default, icon))
            real(default, icon)

        monkeypatch.setattr(root, "iconphoto", spy)
        assert gui_view.set_icon(root)
        assert [default for default, _ in calls] == [True]
        assert [image for _, image in calls] == [fallback]
        assert fallback.height() == 1
    finally:
        root.destroy()


@pytest.mark.gui
def test_a_window_without_a_loadable_icon_still_launches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("tkinter")
    import tkinter as tk

    from zipseal import gui_view

    svg = tmp_path / "icon.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    monkeypatch.setattr(gui_view, "ICON", svg)

    fail_every_load = False

    def photo_image(master: tk.Misc, file: str, format: str | None = None) -> tk.PhotoImage:
        if fail_every_load or (format or "").startswith("svg"):
            raise tk.TclError(f'could not load "{file}"')
        raise AssertionError(f"the PNG is missing, so it must not be loaded: {file}")

    root = tk.Tk()
    try:
        monkeypatch.setattr(gui_view.tk, "PhotoImage", photo_image)
        calls: list[tuple[bool, tk.PhotoImage]] = []

        def record(default: bool, icon: tk.PhotoImage) -> None:
            calls.append((default, icon))

        monkeypatch.setattr(root, "iconphoto", record)
        assert not (tmp_path / "icon.png").exists()
        assert not gui_view.set_icon(root)
        assert calls == []
        _write_png(tmp_path / "icon.png", 1, 1)
        fail_every_load = True
        assert not gui_view.set_icon(root)
        assert calls == []
        assert root.winfo_exists()
    finally:
        root.destroy()
