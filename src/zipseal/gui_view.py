"""The desktop GUI's window (plan: Screen).

This is the only module that imports Tk, and `gui.main` imports it, so a headless
test can use `gui.Controller` alone. Everything here runs on the main loop: the
worker reports through the controller's queue, and this module only reads that
queue with `after()` and never the other way round.
"""

import sys
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from zipseal.errors import UsageError, ZipsealError
from zipseal.gui import (
    CUSTOM_SIZE,
    ICON,
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
from zipseal.options import DEFAULT_EXCLUDES
from zipseal.passwords import Password

APP_ID = "zipseal.gui"
CLIPBOARD_MS = 60_000
POLL_MS = 50


class View:
    """The one window: it reads widgets and shows the queue.

    All of it runs on the main loop, so no widget is ever touched by the worker.
    """

    def __init__(self, root: tk.Tk, controller: Controller | None = None) -> None:
        self.root = root
        self.controller = controller if controller is not None else Controller()
        self._clipboard: str | None = None
        self._clipboard_timer: str | None = None
        self._busy = False

        root.title("zipseal")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        outer = ttk.Frame(root, padding=8)
        outer.grid(sticky="nsew")
        outer.columnconfigure(0, weight=1)

        self._build_inputs(outer, 0)
        self._build_output(outer, 1)
        self._build_options(outer, 2)
        self._build_password(outer, 3)
        self._build_progress(outer, 4)
        self._build_log(outer, 5)
        self._build_actions(outer, 6)

    # ── the screen ────────────────────────────────────────────────────────────

    def _build_inputs(self, parent: tk.Misc, row: int) -> None:
        box = ttk.LabelFrame(parent, text=" Inputs ", padding=6)
        box.grid(row=row, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)
        self.paths = tk.Listbox(box, height=5, selectmode=tk.EXTENDED)
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.paths.yview)
        self.paths.configure(yscrollcommand=scroll.set)
        self.paths.grid(row=0, column=0, rowspan=2, sticky="nsew")
        scroll.grid(row=0, column=1, rowspan=2, sticky="ns")
        buttons = ttk.Frame(box)
        buttons.grid(row=0, column=2, rowspan=2, sticky="n")
        for index, (text, command) in enumerate(
            (
                ("Add files…", self._add_files),
                ("Add folder…", self._add_folder),
                ("Remove", self._remove),
            )
        ):
            ttk.Button(buttons, text=text, command=command).grid(row=index, column=0, sticky="ew")

    def _build_output(self, parent: tk.Misc, row: int) -> None:
        box = ttk.LabelFrame(parent, text=" Output ", padding=6)
        box.grid(row=row, column=0, sticky="ew", pady=4)
        box.columnconfigure(0, weight=1)
        self.output = ttk.Entry(box)
        self.output.grid(row=0, column=0, sticky="ew")
        ttk.Button(box, text="Save as…", command=self._save_as).grid(row=0, column=1)

    def _build_options(self, parent: tk.Misc, row: int) -> None:
        box = ttk.LabelFrame(parent, text=" Options ", padding=6)
        box.grid(row=row, column=0, sticky="ew", pady=4)
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="Max part size").grid(row=0, column=0, sticky="w")
        self.max_size = ttk.Combobox(box, values=list(SIZE_PRESETS), width=16, state="readonly")
        self.max_size.set(SIZE_PRESETS[0])
        self.max_size.grid(row=0, column=1, sticky="w")
        self.max_size.bind("<<ComboboxSelected>>", self._on_size_choice)
        ttk.Label(box, text="Custom size (MB)").grid(row=1, column=0, sticky="w")
        self.custom_mb = ttk.Spinbox(box, from_=1, to=1_000_000, increment=1, width=10)
        self.custom_mb.set("25")
        self.custom_mb.grid(row=1, column=1, sticky="w")
        self.custom_mb.state(["disabled"])
        ttk.Label(box, text="Compression level").grid(row=2, column=0, sticky="w")
        self.level = ttk.Spinbox(box, from_=0, to=9, width=4)
        self.level.set("6")
        self.level.grid(row=2, column=1, sticky="w")
        self.hide_names = tk.BooleanVar()
        ttk.Checkbutton(box, text="Hide names", variable=self.hide_names).grid(
            row=3, column=0, columnspan=2, sticky="w"
        )
        self.follow = tk.BooleanVar()
        ttk.Checkbutton(box, text="Follow symlinks", variable=self.follow).grid(
            row=4, column=0, columnspan=2, sticky="w"
        )
        self.force = tk.BooleanVar()
        ttk.Checkbutton(box, text="Overwrite existing files", variable=self.force).grid(
            row=5, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(box, text="Excludes, one glob per line").grid(
            row=6, column=0, columnspan=2, sticky="w"
        )
        self.excludes = tk.Text(box, height=3, width=32)
        self.excludes.grid(row=7, column=0, columnspan=2, sticky="ew")
        ttk.Label(box, text=f"always skipped: {', '.join(DEFAULT_EXCLUDES)}").grid(
            row=8, column=0, columnspan=2, sticky="w"
        )

    def _on_size_choice(self, _event: object = None) -> None:
        """Switch the MB box on only while `Custom…` is chosen."""
        if self.max_size.get() == CUSTOM_SIZE:
            self.custom_mb.state(["!disabled"])
            self.custom_mb.focus_set()
        else:
            self.custom_mb.state(["disabled"])

    def _build_password(self, parent: tk.Misc, row: int) -> None:
        box = ttk.LabelFrame(parent, text=" Password ", padding=6)
        box.grid(row=row, column=0, sticky="ew", pady=4)
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="Password").grid(row=0, column=0, sticky="w")
        self.password = ttk.Entry(box, show="•")
        self.password.grid(row=0, column=1, sticky="ew")
        ttk.Label(box, text="Confirm").grid(row=1, column=0, sticky="w")
        self.confirm = ttk.Entry(box, show="•")
        self.confirm.grid(row=1, column=1, sticky="ew")
        self.generate = tk.BooleanVar()
        ttk.Checkbutton(
            box, text="Generate a password", variable=self.generate, command=self._mask_fields
        ).grid(row=2, column=0, columnspan=2, sticky="w")
        self._mask_fields()

    def _build_progress(self, parent: tk.Misc, row: int) -> None:
        box = ttk.Frame(parent)
        box.grid(row=row, column=0, sticky="ew", pady=4)
        box.columnconfigure(0, weight=1)
        self.bar = ttk.Progressbar(box, mode="indeterminate")
        self.bar.grid(row=0, column=0, sticky="ew")
        self.status = tk.StringVar()
        ttk.Label(box, textvariable=self.status).grid(row=1, column=0, sticky="w")

    def _build_log(self, parent: tk.Misc, row: int) -> None:
        box = ttk.LabelFrame(parent, text=" Log ", padding=6)
        box.grid(row=row, column=0, sticky="nsew", pady=4)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        parent.rowconfigure(row, weight=1)
        self.log = ScrolledText(box, height=8, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")

    def _build_actions(self, parent: tk.Misc, row: int) -> None:
        box = ttk.Frame(parent)
        box.grid(row=row, column=0, sticky="e")
        self.dry_button = ttk.Button(box, text="Dry run", command=lambda: self._start(dry_run=True))
        self.dry_button.grid(row=0, column=0)
        self.run_button = ttk.Button(
            box, text="Create archive", command=lambda: self._start(dry_run=False)
        )
        self.run_button.grid(row=0, column=1)
        self.cancel_button = ttk.Button(box, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_button.grid(row=0, column=2)

    # ── window to plain values ────────────────────────────────────────────────

    def _read_form(self, *, dry_run: bool) -> JobSpec:
        """The window, as the plain values the controller takes."""
        output = self.output.get().strip()
        if not output:
            raise UsageError("choose an output name")
        return JobSpec(
            paths=[Path(self.paths.get(i)) for i in range(self.paths.size())],
            output=Path(output),
            max_size=parse_max_size(self.max_size.get(), self.custom_mb.get()),
            level=parse_level(self.level.get()),
            excludes=self.excludes.get("1.0", "end"),
            follow_symlinks=self.follow.get(),
            hide_names=self.hide_names.get(),
            force=self.force.get(),
            dry_run=dry_run,
        )

    def _add(self, paths: list[Path]) -> None:
        have = {self.paths.get(i) for i in range(self.paths.size())}
        for path in paths:
            if str(path) not in have:
                self.paths.insert("end", str(path))
                have.add(str(path))

    def _add_files(self) -> None:
        self._add([Path(name) for name in filedialog.askopenfilenames(title="Add files")])

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Add folder")
        if folder:
            self._add([Path(folder)])

    def _remove(self) -> None:
        for index in reversed(self.paths.curselection()):
            self.paths.delete(index)

    def _save_as(self) -> None:
        chosen = filedialog.asksaveasfilename(
            title="Save as", defaultextension=".zip", initialfile=self.output.get()
        )
        if chosen:
            self.output.delete(0, "end")
            self.output.insert(0, chosen)

    def _mask_fields(self) -> None:
        """Keep both password fields masked, and untypeable while generating."""
        state = "disabled" if self.generate.get() else "normal"
        self.password.configure(state=state)
        self.confirm.configure(state=state)

    # ── running ───────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Show the window and start polling the queue."""
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        # macOS sends the app menu's Quit (Cmd-Q) here, so it gets the same guard.
        self.root.createcommand("::tk::mac::Quit", self._quit)
        self.root.after(POLL_MS, self._poll)
        self.root.mainloop()

    def _start(self, *, dry_run: bool) -> None:
        """Read the window, ask about overwriting, then hand the job to the worker."""
        try:
            spec = self._read_form(dry_run=dry_run)
            # A dry run writes nothing, so it has nothing to overwrite.
            clashes = [] if spec.dry_run else existing_outputs(build_options(spec))
        except ZipsealError as exc:
            self._report(str(exc))
            return
        if clashes and not spec.force:
            # The plan asks instead of failing (SPEC.md §6.5): force is what the
            # core needs before it replaces existing outputs.
            if not messagebox.askyesno("zipseal", _clash_message(clashes)):
                return
            spec = replace(spec, force=True)
        try:
            self.controller.start(
                spec,
                generate=self.generate.get(),
                password=self.password.get(),
                confirm=self.confirm.get(),
            )
        except UsageError as exc:
            self._report(str(exc))
            return
        self._set_busy(True)

    def _cancel(self) -> None:
        """Ask the worker to stop. A `Stopped` event follows once it has cleaned up."""
        self.controller.cancel()
        self.cancel_button.configure(state="disabled")
        self.status.set("cancelling …")

    def _poll(self) -> None:
        """Drain the queue on the main loop, then look again in a moment."""
        for event in self.controller.poll():
            self._handle(event)
        self.root.after(POLL_MS, self._poll)

    def _handle(self, event: Log | ProgressUpdate | Error | Stopped | Done) -> None:
        if isinstance(event, Log):
            self._append_log(event.line)
        elif isinstance(event, ProgressUpdate):
            self._show_progress(event.phase, event.number, event.value)
        elif isinstance(event, Error):
            self._failed(event.message)
        elif isinstance(event, Stopped):
            self._stopped(event.message)
        else:
            self._finished()

    def _show_progress(self, phase: str, number: int, value: int) -> None:
        if phase == "started":
            self.status.set(f"writing part {number} …")
        elif phase == "bytes":
            self.status.set(f"{value:,} bytes written")
        elif phase == "verifying":
            self.status.set(f"verifying {value} part(s) …")
        else:
            self.status.set(f"part {number} verified, {value:,} bytes")

    def _finished(self) -> None:
        """A run succeeded: clear the fields, then show a generated password."""
        self._set_busy(False)
        self._clear_fields()
        password = self.controller.take_generated_password()
        if password is not None:
            self._password_modal(password)

    def _failed(self, message: str) -> None:
        """A run failed: clear the fields and show the message the core gave."""
        self._set_busy(False)
        self._clear_fields()
        self.controller.clear_password()
        self._report(message)

    def _stopped(self, message: str) -> None:
        """The user cancelled: clear the fields, and say so without an error dialog."""
        self._set_busy(False)
        self._clear_fields()
        self.controller.clear_password()
        self.status.set(message)
        self._append_log(message)

    def _report(self, message: str) -> None:
        """Show one message, in the log area and in a dialog."""
        self._append_log(message)
        messagebox.showerror("zipseal", message)

    def _clear_fields(self) -> None:
        """Blank both password fields after every run, success or failure."""
        # Re-enable the fields first: a disabled entry ignores `delete`.
        self.generate.set(False)
        self._mask_fields()
        self.password.delete(0, "end")
        self.confirm.delete(0, "end")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (self.dry_button, self.run_button):
            widget.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        if busy:
            self.bar.start(10)
        else:
            self.bar.stop()

    def _append_log(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"{line}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _quit(self) -> None:
        """Close the window, clearing the clipboard first if it holds a password.

        Not while a job runs: closing would kill the worker, and a generated
        password would be lost before its modal could show it.
        """
        if self._busy:
            messagebox.showinfo(
                "zipseal", "An archive is being written. Cancel it, or wait for it to finish."
            )
            return
        self._clear_clipboard()
        self.root.destroy()

    # ── the generated password ────────────────────────────────────────────────

    def _password_modal(self, password: Password) -> None:
        """Show the generated password once, with a copy button and a warning.

        This is the one place the value is ever displayed, and it is only reached
        after every part has verified. The clipboard is cleared when the modal
        closes and again 60 seconds after a copy, both best effort.
        """
        top = tk.Toplevel(self.root)
        top.title("zipseal: generated password")
        top.transient(self.root)
        top.resizable(False, False)
        top.columnconfigure(0, weight=1)

        ttk.Label(
            top,
            text="This password is shown once. Send it through a different channel than "
            "the archive, then close this window.",
            wraplength=380,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=8)
        ttk.Label(
            top,
            text="Other apps can read the clipboard. zipseal clears it when this window "
            "closes, and 60 seconds after you copy it.",
            wraplength=380,
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=8)
        shown = ttk.Entry(top, width=32)
        shown.insert(0, password.value)
        shown.configure(state="readonly")
        shown.grid(row=2, column=0, columnspan=2, padx=8)

        def close() -> None:
            self._clear_clipboard()
            top.destroy()

        # Selected, so the keyboard can copy it without a "show password" toggle.
        # A keyboard copy goes through `_copy` too, so it gets the same cleanup.
        shown.bind("<<Copy>>", lambda _event: (self._copy(shown.get()), "break")[1])
        shown.select_range(0, "end")
        shown.focus_set()
        top.grab_set()
        ttk.Button(top, text="Copy", command=lambda: self._copy(shown.get())).grid(
            row=3, column=0, padx=8, pady=8
        )
        ttk.Button(top, text="Close", command=close).grid(row=3, column=1, padx=8, pady=8)
        top.protocol("WM_DELETE_WINDOW", close)

    def _copy(self, value: str) -> None:
        """Put the password on the clipboard, and clear it again after a minute."""
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self._clipboard = value
        # Restart the timer, so an older copy's timer cannot clear this one early.
        if self._clipboard_timer is not None:
            self.root.after_cancel(self._clipboard_timer)
        self._clipboard_timer = self.root.after(CLIPBOARD_MS, self._clear_clipboard)

    def _clear_clipboard(self) -> None:
        """Clear the clipboard only if it still holds the password.

        Another app may own it now, and reading it can fail, so this is best
        effort: it compares inside a `TclError` guard and gives up quietly.
        """
        secret, self._clipboard = self._clipboard, None
        if self._clipboard_timer is not None:
            self.root.after_cancel(self._clipboard_timer)
            self._clipboard_timer = None
        if secret is None:
            return
        try:
            if self.root.clipboard_get() == secret:
                self.root.clipboard_clear()
        except tk.TclError:
            pass


def _clash_message(clashes: list[Path]) -> str:
    """The overwrite question's text (SPEC.md §6.5)."""
    listing = "\n".join(f"  {path}" for path in clashes[:5])
    more = f"\n  … and {len(clashes) - 5} more" if len(clashes) > 5 else ""
    return f"these files already exist:\n{listing}{more}\n\nOverwrite them?"


def _set_app_id() -> None:
    """Give the process its own Windows taskbar identity, so it does not group
    under python.exe's icon. It must run before the first window exists."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass


def set_icon(root: tk.Tk) -> bool:
    """Show the zipseal icon in the Dock, taskbar and title bar.

    Tk 9 reads SVG. An older Tk cannot, and then the default icon stays: an icon
    is never worth failing a launch. Returns whether the icon was set.
    """
    try:
        image = tk.PhotoImage(master=root, file=str(ICON), format="svg -scaletoheight 256")
    except tk.TclError:
        return False
    root.iconphoto(True, image)
    return True


def run() -> int:
    """Open the window: the `zipseal-gui` script entry point."""
    _set_app_id()
    root = tk.Tk()
    set_icon(root)
    View(root).run()
    return 0
