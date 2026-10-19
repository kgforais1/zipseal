"""The window icon ships inside the package and is set when Tk can read SVG.

The package checks import no Tk, so they run on a Python without it. The window
checks import Tk inside each test and carry the `gui` marker.
"""

import subprocess
import zipfile
from pathlib import Path

import pytest

from zipseal.gui import ICON

REPO = Path(__file__).resolve().parent.parent


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
def test_set_icon_falls_back_when_svg_is_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("tkinter")
    import tkinter as tk

    from zipseal import gui_view

    def no_svg(*_args: object, **_kwargs: object) -> object:
        raise tk.TclError('image format "svg" is not supported')

    root = tk.Tk()
    try:
        monkeypatch.setattr(gui_view.tk, "PhotoImage", no_svg)
        assert not gui_view.set_icon(root)
    finally:
        root.destroy()
