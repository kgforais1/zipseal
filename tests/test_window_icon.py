"""The window icon ships inside the package and is set when Tk can read SVG."""

import subprocess
import tkinter as tk
import zipfile
from pathlib import Path

import pytest

from zipseal import gui_view

REPO = Path(__file__).resolve().parent.parent


def test_icon_is_an_svg_next_to_the_module() -> None:
    text = gui_view.ICON.read_text()
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
def test_set_icon_on_tk_9() -> None:
    root = tk.Tk()
    try:
        if tk.TkVersion < 9:
            pytest.skip("Tk 8.x cannot read SVG")
        assert gui_view.set_icon(root)
    finally:
        root.destroy()


@pytest.mark.gui
def test_set_icon_falls_back_when_svg_is_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_svg(*_args: object, **_kwargs: object) -> tk.PhotoImage:
        raise tk.TclError('image format "svg" is not supported')

    root = tk.Tk()
    try:
        monkeypatch.setattr(gui_view.tk, "PhotoImage", no_svg)
        assert not gui_view.set_icon(root)
    finally:
        root.destroy()
