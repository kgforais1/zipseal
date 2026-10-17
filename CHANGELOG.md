# Changelog

All notable user-facing changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and this project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Password guidance in `user-docs/security.md`: concrete minimums (16+ random
  characters, or five or more unrelated words) for people who must choose
  their own password instead of using `--generate-password`, with the
  reasoning behind them and how they compare to a generated password.

- `zipseal-gui`, a Tkinter window over the same core. It adds files and
  folders, sets the part size, level, excludes and name hiding, runs a dry
  run, and shows progress and warnings in a log area (`user-docs/gui.md`).
- A generated password is shown once in a modal after a successful run, never
  in the log area, and the clipboard it may be copied to is cleared soon
  after.
- The window asks before replacing outputs from an earlier run, instead of
  stopping, and nothing is saved between sessions.

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
