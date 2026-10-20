# The zipseal window

Last reviewed: 2026-10-18

`zipseal-gui` opens a window that does the same job as the `zipseal` command.
The archives are the same either way, and the same rules apply. Options the
window does not show keep their usual defaults.

## Start it

On macOS, double-click `zipseal-gui.command` in a clone of the project. Finder
opens Terminal, and Terminal opens the zipseal window. Leave the Terminal
window open: it shows any error, and closing it closes zipseal. The first run
gives the file the zipseal icon. It runs zipseal on a Python that uv
manages, because those always include Tk, so the first run may pause while uv
downloads one. On that Python, the window shows the zipseal icon in the Dock
or taskbar.

If the copy came from a downloaded ZIP rather than `git clone`, macOS may
refuse to open it. Open System Settings → Privacy & Security, and press
`Open Anyway` next to the message about `zipseal-gui.command`
([Apple's guide](https://support.apple.com/en-ie/102445)). From a terminal,
`xattr -d com.apple.quarantine zipseal-gui.command` does the same.

From a terminal in a clone of the project:

```sh
uv run zipseal-gui
```

That runs it without installing anything. To put it on your `PATH`, next to
the `zipseal` command:

```sh
scripts/install.sh
```

That installs `zipseal-gui` as an editable tool, so it picks up changes to the
project. On macOS it also gives `zipseal-gui.command` its icon. `scripts/install.sh --release` installs a snapshot instead, and
`scripts/install.sh --uninstall` removes both commands. You need Python 3.11
or later and [`uv`](https://docs.astral.sh/uv/). The window needs a display:
over an SSH session, use the CLI.

## Add what you want to archive

`Add files…` picks individual files. `Add folder…` picks a folder, and
everything inside it is included. `Remove` takes the selected rows out of the
list. A folder is stored under its own name, so `~/data/reports` becomes
`bundle.zip` → `reports/…`; a file is stored at the top level under its own
name.

Add as many files and folders as you like. A file already in the list is not
added twice.

## Choose where it goes

Type the output name, or press `Save as…` and pick one. The name usually ends
in `.zip`. zipseal checks the folder can hold the output before it writes
anything.

## Options

| Control | What it does |
|---|---|
| `Max part size` | The cap for each part. `no limit` writes one zip. The presets run from 10 MB to 20 GB. Choose `Custom…` to type your own. |
| `Custom size (MB)` | Used only with `Custom…`. A number of megabytes, where 1 MB is 1,000,000 bytes, as in the CLI. Decimals such as `7.5` work. |
| `Compression level` | `0` to `9`. `6` is the default and `0` stores files without compressing them. |
| `Hide names` | Nest each part's files inside one encrypted `payload.zip`, so names, sizes and dates are not readable without the password. |
| `Follow symlinks` | Follow symlinks. Without it, they are skipped with a note in the log. |
| `Overwrite existing files` | Replace outputs from an earlier run. Old outputs are restored if this run fails. |
| `Excludes` | One glob per line, such as `*.tmp`. `.DS_Store`, files starting with `._` and `Thumbs.db` are always skipped. |

With several parts, they are named `bundle-volume01-of-03.zip` and so on. Every
part opens on its own, with the same password.

## Password

Type the password twice, or tick `Generate a password` and let zipseal make a
random 24-character one. Both fields are always masked, and there is no button
to reveal what you typed. The two boxes are switched off while
`Generate a password` is ticked.

An empty password is refused, and a short one is warned about in the log,
before anything is written. AES-256 (AE-2) derives its key with PBKDF2 at only
1,000 iterations, so a guessable password is the weak point. Prefer a generated
one. Send it through a different channel than the zip, such as a phone call.

## Run it

`Dry run` lists what would be archived and the most parts it could take. It
writes nothing and asks for no password.

`Create archive` does the work. The bar moves while parts are written, the
status line says which part is being written or verified, and the log area
collects the notes the command prints on stderr. Warnings, such as a skipped
symlink or a password shorter than 12 characters, appear there too.

Both fields are cleared after every run, whether it worked or not.

### The generated password

After a successful run, a window shows the generated password once. Copy it
with the `Copy` button or with your keyboard, then close the window.

Either way of copying puts the password on your clipboard, and other apps
can read a clipboard. zipseal clears it when you close that window, and again 60 seconds
after you copy. Other apps can still take it in between, so copy it and move
on. The password is never written to the log area.

You cannot close the main window while an archive is being written. That
keeps a generated password from being lost before it is shown.

### If something goes wrong

A dialog says what happened, in the same words the command would use. Nothing
is written: parts are made under a temporary `.partial` name and only renamed
after they are verified, and every `.partial` file is removed when a run
fails. The log area says when they appear. Do not rename, move or open them
while the run works. If an earlier run was killed and left `.partial` files in
the way, the next run stops and lists them. Delete those, then try again.

Press Cancel to stop a run. It takes effect at the next progress checkpoint.
Then zipseal removes its `.partial` files, writes no archive, and says so in
the log area. If zipseal is already publishing the parts, the run finishes,
the archive stays, and the status says `done`. The window cannot close while a
run works, so cancel it first. A dry run cannot be cancelled, so wait for it to
finish.

## What the window keeps

Nothing. No settings are saved, so your password, output name and options
last as long as the window does.

## See also

- [Quick start](quick-start.md) for the same job from a terminal.
- [CLI reference](cli.md) for every option.
- [Security notes](security.md) for what is protected and what is visible.
