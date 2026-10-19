# Plan: Double-clickable GUI launcher

Date: 2026-10-18
Status: in-progress
Linked: branch `feat/gui-command-launcher`

## Goal

Let a macOS user open the zipseal window by double-clicking a file in Finder,
with no terminal typing. This is a stopgap before the signed `.app` in
`TODO.md`, which stays open.

## Design

Add `zipseal-gui.command` at the repo root, where Finder users see it first.
Finder opens a `.command` file in Terminal and runs it as a shell script.

The script:

1. Uses `#!/bin/sh` and `set -eu`, like `scripts/install.sh`.
2. Finds the repo from its own path, so it works from any clone location.
3. Finds `uv`. Finder starts a non-login shell, so `~/.local/bin`,
   `/opt/homebrew/bin` and `/usr/local/bin` may be missing from `PATH`. Try
   `command -v uv` first, then those folders and `~/.cargo/bin`. Store the
   result in `$uv`. Use `$HOME`, never a literal home path, so `check-personal-data`
   passes.
4. Runs `exec "$uv" run --managed-python --project "$repo" zipseal-gui`.
   uv-managed Pythons always include Tk. Homebrew's Python lacks it unless
   `python-tk` is installed. It runs the resolved path, because a fallback
   folder is not on `PATH`. This always uses the
   clone's current source and needs no prior `scripts/install.sh`.
5. If `uv` is missing, prints where to get it and waits for Return, so the
   Terminal window does not vanish before the user reads the message. The
   wait tolerates EOF on stdin (`read _ || true`), so it cannot trip
   `set -e` or hang.

It passes no arguments to the GUI, so no password can reach argv.

The Terminal window stays open while the GUI runs and shows any Python
traceback. Closing that window quits the GUI. That matches the existing
"closing during a run" warning in `user-docs/gui.md`. Hiding Terminal with
`osascript` or `nohup` is out of scope because it hides errors and is fragile.

Git stores the file as mode `100755`, so a clone keeps it executable. A clone
gets no quarantine flag. A GitHub "Download ZIP" copy does, and current
macOS may block it outright. The docs point to System Settings → Privacy &
Security → Open Anyway ([Apple guide](https://support.apple.com/en-ie/102445)),
and mention `xattr -d com.apple.quarantine zipseal-gui.command` for terminal
users.

## Icon and README

`assets/icon.svg` is the project icon. It is hand-written SVG, because
`.forbidden-paths` blocks PNG and other raster images. Its root carries
`width="128" height="128"`, so the README shows it at that size without
inline HTML, which markdownlint forbids (MD033).

`scripts/set-icon.sh FILE` gives FILE the icon on macOS. It loads the SVG with
`NSImage` and calls `NSWorkspace.setIcon(_:forFile:)` through
`osascript -l JavaScript`. Verified on macOS 26 on 2026-10-18. The icon lives
in extended attributes, so git sees no change. On other systems, or when it
fails, the script prints nothing and exits 0. An icon is never worth blocking
a launch.

Two callers use it:

- `scripts/install.sh` sets the icon on `zipseal-gui.command` after install.
- The launcher sets its own icon on first run, when the file has no
  `com.apple.ResourceFork` attribute yet. A fresh clone has none.

The README gets the icon at the top, then badges for CI, dependency audit,
Python 3.11+, AES-256 and the MIT license. It also gains a short GUI pointer
and a macOS launcher section under Install.

## Tasks

- [x] Write `zipseal-gui.command` and commit it with mode `100755`
      (`git update-index --chmod=+x` if needed).
- [x] Add `tests/test_launcher.py`:
  - [x] The file is tracked as executable and starts with `#!/bin/sh`.
  - [x] `sh -n` accepts it.
  - [x] Every subprocess test passes a `timeout` and uses
        `stdin=DEVNULL` unless it feeds input, so a broken prompt cannot hang
        CI.
  - [x] With a stub `uv` first on `PATH`, the script calls
        `uv run --managed-python --project <repo> zipseal-gui` with no other
        arguments.
  - [x] With `uv` only in `$HOME/.local/bin` (a `tmp_path` HOME) and not on
        `PATH`, the script still runs that stub. This catches a bare
        `exec uv`.
  - [x] Copy the launcher into a `tmp_path` folder whose name has a space,
        run it from an unrelated working directory, and assert the exact
        `--project` path.
  - [x] With no `uv` anywhere (`PATH` and `HOME` pointed at empty
        `tmp_path` folders), it exits non-zero and names the install URL.
        Run it once with a newline and once with EOF on stdin. `PATH` holds
        only links to the launcher's tools (`dirname`, `basename`, `xattr`),
        so a system `uv` cannot leak in. Skip the test when `uv`
        exists in `/opt/homebrew/bin` or `/usr/local/bin`, because the
        script checks those absolute folders and the test cannot hide them.
- [x] Generate candidate icons with Gemini 3.8 Flash (High) via Antigravity
      into `.context/icons/`. The user picks one, and it goes to
      `assets/icon.svg`.
- [x] Write `scripts/set-icon.sh` and call it from `scripts/install.sh` and
      the launcher's first run.
- [x] Test `set-icon.sh`: it exits 0 on Linux without touching the file.
      On macOS (skipped elsewhere), a `tmp_path` copy gains
      `com.apple.ResourceFork` and its bytes are unchanged.
- [x] Polish `README.md`: icon, badges, GUI and launcher sections.
- [ ] Double-click it in Finder on macOS and confirm the window opens. This
      is the manual check that tests cannot cover. `open zipseal-gui.command`,
      which takes the same Terminal path, started the GUI on 2026-10-18, and
      `scripts/install.sh` gave the file its icon with git status unchanged.
      A real double-click by the user is still open.
- [ ] Repeat with a copy from a browser-downloaded ZIP to confirm the
      Gatekeeper steps in the docs.
- [x] Update `user-docs/gui.md` "Start it", and bump `Last reviewed`.
- [x] Mention the launcher, `assets/` and `set-icon.sh` in the `AGENTS.md`
      commands and layout. Bump both `Last reviewed` dates after re-reading.
- [x] Log it in `CHANGELOG.md`.
- [x] Run `uv run pytest` and `pre-commit run --all-files`.
- [ ] Run the completion steps in `dev-docs/README.md`.

## Decisions

- The file lives at the repo root, because Finder users see it first there.
- It always uses `uv run`, not an installed `zipseal-gui`. `uv run` matches
  the clone, and the editable install points at the same source anyway.

## Review

Codex (GPT-6.1-Sol, low) reviewed the draft on 2026-10-18. Its three findings
are folded in above: run the resolved `$uv` path, document Open Anyway for
quarantined copies, and test a spaced clone path, a foreign working
directory, EOF on stdin and subprocess timeouts.

Sourcery and Greptile reviewed PR #9. Their fixes: run uv-managed Python so
Tk is present, also look in `~/.cargo/bin`, build the test `PATH` from links
to the launcher's tools so a system `uv` cannot leak in, assert the full argv
in every launcher test, and skip the icon test only when an independent
AppKit probe shows the session cannot set icons.
