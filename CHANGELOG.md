# Changelog

All notable user-facing changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and this project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `zipseal-gui.command`: double-click it in Finder to open the zipseal window
  from a clone, with no install step. It finds `uv` even when Finder's shell
  has it off `PATH`, and gives itself the zipseal icon on first run.
  `scripts/install.sh` sets the icon too (`user-docs/gui.md`,
  [plan](dev-docs/plans/archive/2026-10-18-gui-command-launcher.md)).
- The window's `Max part size` now offers presets from 10 MB to 20 GB, plus
  `Custom…` with a clearly labeled `Custom size (MB)` box. The list no longer
  accepts free text.
- The zipseal window shows the project icon in the macOS Dock, the Windows
  taskbar and the title bar, when Python's Tk is version 9 or later
  (uv-managed Pythons are). An older Tk keeps its default icon.
- A project icon (`src/zipseal/icon.svg`) and CI, audit, Python, AES-256 and
  license badges at the top of the README.

- Password guidance in `user-docs/security.md`: concrete minimums (16+
  characters drawn from the 62 letters and digits, or five unrelated words)
  for people who must choose their own password instead of using
  `--generate-password`, with the reasoning behind them and how they compare
  to a generated password.

- `zipseal-gui`, a Tkinter window over the same core. It adds files and
  folders, sets the part size, level, excludes and name hiding, runs a dry
  run, and shows progress and warnings in a log area (`user-docs/gui.md`).
- A generated password is shown once in a modal after a successful run, never
  in the log area, and the clipboard it may be copied to is cleared soon
  after.
- The window asks before replacing outputs from an earlier run, instead of
  stopping, and nothing is saved between sessions.

### Fixed

- `Save as…` now opens in the output's folder with only its file name filled
  in. Before, the name field held the whole old path, so a typed name was
  added to it.

### Changed

- Split outputs are now named `NAME-volumeNN-of-MM.zip` instead of
  `NAME-partNN-of-MM.zip`. The existing-output check and `--force` match the
  new names only, so old `-part` files are left alone. Old `-part` archives
  and `.partial` files are still skipped as inputs, old `.partial` files still
  block a run, and a run lists old `-part` archives in a warning.
- Temporary files are now named `NAME-volumeNN.zip.temp` instead of
  `.partial`. Old `.partial` files still stop a run and are still skipped as
  inputs.
- The window has a Cancel button while a run works. It stops the run and
  removes its `.temp` files, with no error dialog.
- In a terminal, a run says that Ctrl-C cancels it. Ctrl-C already removed the
  run's temporary files.
- A run now prints a notice before its `.temp` files appear, asking you not
  to rename, move or open them until it finishes.

## [0.1.0] - 2026-10-08

### Added

- `zipseal PATH... -o OUT.zip` writes one AES-256 (WinZip AE-2) zip,
  verifies it, and publishes it without overwriting existing files.
- Password from a prompt, an environment variable, a file, or
  `--generate-password`.
- `--max-size` splits output into parts that each open on their own and
  never exceed the cap. `--order size` packs into fewer parts.
- `--hide-names` nests each part's files in an inner zip inside one encrypted
  `payload.zip`, so names, sizes and dates are hidden without the password.
- `--manifest` adds `MANIFEST.txt` to every part, listing which part holds
  each file.
- `--dry-run`, `--exclude`, `--follow-symlinks`, `--level`, `--force` and
  `--no-verify`.

### Fixed

- A file name containing bytes that look like a Zip64 locator no longer makes verification fail.
