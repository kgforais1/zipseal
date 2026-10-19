"""The window's Cancel button. These need a real Tk display, so they carry `gui`."""

import pytest


@pytest.fixture
def view():  # type: ignore[no-untyped-def]
    pytest.importorskip("tkinter")
    import tkinter as tk

    from zipseal import gui_view

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
