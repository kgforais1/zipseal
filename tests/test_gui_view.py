"""The window's Cancel and Save as wiring. These need a real Tk display, so they carry `gui`."""

import pytest


@pytest.fixture
def view(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    pytest.importorskip("tkinter")
    import tkinter as tk

    from zipseal import gui_view

    def no_dialogs(*args: object, **_kwargs: object) -> None:
        pytest.fail(f"unexpected dialog: {args}")  # a real one would wait forever

    for name in ("showerror", "showinfo", "askyesno"):
        monkeypatch.setattr(gui_view.messagebox, name, no_dialogs)
    root = tk.Tk()
    root.withdraw()
    try:
        yield gui_view.View(root)
    finally:
        root.destroy()


@pytest.mark.gui
def test_cancel_is_enabled_only_for_a_real_run(view) -> None:  # type: ignore[no-untyped-def]
    assert str(view.cancel_button["state"]) == "disabled"
    view._set_busy(True, cancellable=False)  # a dry run
    assert str(view.cancel_button["state"]) == "disabled"
    view._set_busy(True, cancellable=True)
    assert str(view.cancel_button["state"]) == "normal"
    view._set_busy(False)
    assert str(view.cancel_button["state"]) == "disabled"


@pytest.mark.gui
def test_a_run_that_finishes_after_cancel_does_not_say_cancelling(view) -> None:  # type: ignore[no-untyped-def]
    view._set_busy(True, cancellable=True)
    view._cancel()
    assert view.status.get() == "cancelling …"
    view._finished()
    assert view.status.get() == "done"


@pytest.mark.gui
@pytest.mark.parametrize(("dry_run", "state"), [(True, "disabled"), (False, "normal")])
def test_start_enables_cancel_only_for_a_real_run(
    view, tmp_path, monkeypatch: pytest.MonkeyPatch, dry_run: bool, state: str
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(view.controller, "start", lambda *_a, **_k: None)
    view._add([tmp_path])
    view.output.insert(0, str(tmp_path / "b.zip"))
    view._start(dry_run=dry_run)
    assert str(view.cancel_button["state"]) == state


@pytest.mark.gui
def test_save_as_passes_the_folder_and_a_bare_name(
    view, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from zipseal import gui_view

    seen: dict[str, object] = {}

    def fake_dialog(**kwargs: object) -> str:
        seen.update(kwargs)
        return str(tmp_path / "new.zip")

    monkeypatch.setattr(gui_view.filedialog, "asksaveasfilename", fake_dialog)
    view.output.insert(0, str(tmp_path / "old.zip"))
    view._save_as()
    assert seen["initialdir"] == str(tmp_path)
    assert seen["initialfile"] == "old.zip"
    assert view.output.get() == str(tmp_path / "new.zip")
