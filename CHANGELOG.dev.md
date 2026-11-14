# Developer changelog

Internal changes that users cannot see: harness, hooks, CI, tests, docs-only
edits and refactors. User-visible changes go in [`CHANGELOG.md`](CHANGELOG.md).

## [Unreleased]

### Added

- A `build` dependency group pinned to `pyinstaller==6.22.3`, locked in
  `uv.lock`, for the frozen GUI executables; builds run as
  `uv run --group build` (plan: `dev-docs/plans/2026-11-02-gui-executables.md`).
- Artifact ignore rules for those executables: `.gitignore` and
  `.forbidden-paths` gain `*.dmg`, `*.msi`, `*.exe`, `*.AppImage` and
  `*.tar.gz`, and `.forbidden-paths` also gains `build/` and `dist/`, so a
  force-added build output cannot be committed.
  `tests/test_packaging.py` exercises the hook against a synthetic `dist/`
  artifact in a throwaway repository.

- `packaging/`: the pieces the test list can check without freezing an app:
  `run_gui.py` (the PyInstaller entry point, guarded so importing it opens no
  window), `build.py` (CPython 3.13.17 from python-build-standalone
  `20261021`, a version reader, the Info.plist and
  Windows version-resource substitution, the `.spec`'s `datas`, and a
  preflight that refuses any other interpreter), an empty macOS
  `entitlements.plist`, the Linux `zipseal-gui.desktop` and an executable
  `AppRun`, and `pyproject.toml`'s `[tool.basedpyright].include` plus the
  basedpyright hook now covering `packaging/`.

- `packaging/icons.py`: the icon rasters are now generated at build time from
  `src/zipseal/icon.svg` rather than checked in, so `*.png` stays a forbidden
  path and no raster enters the repository. The toolchain is one pinned
  `resvg` release (`v0.50.0`), fetched for the build host into gitignored
  `build/tools/` and sha256-checked before the archive is extracted or its
  binary executed: resvg publishes no checksum file with a release, so the
  three digests (macOS arm64, Windows x64, Linux x86_64) were computed from
  the downloaded assets. Pillow is the second pinned build tool -
  `pillow==13.0.0` joins `pyinstaller==6.22.3` in the `build` dependency group
  and `uv.lock` - and it packs the multi-size `.ico`; macOS `iconutil` builds
  the `.icns` for a macOS target only. Everything lands in `build/icons/`,
  where `icon.png` is both the fallback `gui_view.set_icon` reads when Tk
  cannot load the SVG and the Linux desktop icon. `packaging/build.py`
  generates those icons after the interpreter check and before the PyInstaller
  freeze; a missing `build/icons/icon.png` fails there with an explicit
  message. `--target` has to be the machine's own platform.
  `tests/test_packaging_icons.py` loads `icons.py` by path, the way
  `tests/test_packaging.py` loads `build.py`, and covers the checksum
  mismatch (the asset is deleted and never executed), the `.ico` packing
  (the output lands under the directory the
  function was given, never under `src/`) and that no test reaches the network;
  the `.ico` test needs Pillow, so it runs where the `build` group is synced
  and skips where it is not. The download speaks https only to GitHub's
  release hosts and unpacking writes the bare `resvg` binary, so `ruff.toml`
  does not suppress the fetch (`S310`) or extract (`S202`) checks for
  `packaging/**`. The release binaries are not static
  ones: the Linux asset links glibc, provided by the pinned build container,
  and the macOS asset links libSystem.

- `packaging/zipseal-gui.spec` and `packaging/build.py`'s freeze step: an
  onedir, windowed PyInstaller build of `packaging/run_gui.py` that bundles the
  SVG and the generated PNG under `_MEIPASS/zipseal/`, with `pytest`,
  `hypothesis`, `basedpyright` and `yaml` excluded, UPX left off, and no codesign identity.
  The spec loads `build.py` by path and reads its target and version from the
  environment `build.py` sets; only a `macos` target gets a `zipseal-gui.app`
  bundle. Before freezing, `build.py` opens and destroys a Tk root and fails
  unless the Tcl and Tk libraries resolve inside `sys.base_prefix`, so a host
  Tcl/Tk cannot reach the bundle. A missing display says to run under
  `xvfb-run` instead of looking like a broken Tcl/Tk. The version is checked
  before icons are generated. PyInstaller writes `dist/<version>.partial` and
  that replaces `dist/<version>/` only after the freeze succeeds, with
  `build/pyinstaller` as the work path. `--skip-sign`
  is required until signing exists. A `tests/test_packaging.py` case builds a
  fake `_MEIPASS` tree and asserts `gui.ICON` and its PNG sibling resolve
  inside it, and the freeze and preflight tests stub `subprocess` and
  `tkinter`, so no window opens and no PyInstaller run happens.

- `latest-deps.yml`: a weekly run (and on demand) that re-resolves uv.lock
  with `uv lock --upgrade` in the runner only, logs which versions moved, and
  runs the fast tests and basedpyright, so an upstream release that breaks
  zipseal shows up before the next lock refresh. The sync includes the
  `build` group, because basedpyright covers `packaging/` and Pillow is only
  there. A failing run is the notification, as in `dependency-audit.yml`.
- `tests/test_launcher.py` covers `zipseal-gui.command` (uv on and off
  `PATH`, a spaced clone path, a foreign working directory, no uv with
  Return or EOF) and `scripts/set-icon.sh`. `scripts/install.sh` now sets the
  launcher's icon ([plan](dev-docs/plans/archive/2026-10-18-gui-command-launcher.md)).

- `dependency-audit.yml`: re-runs ci.yml's uv.lock `pip-audit` weekly, so a
  new advisory fails a scheduled run on a quiet repo, and checks the
  SHA-pinned actions with zizmor's `known-vulnerable-actions` audit on PRs and
  weekly (Dependabot alerts never cover SHA-pinned actions).
- Shared core for both front ends (`Options` in `options.py`, `run_job` in
  `job.py`), so the CLI and the GUI cannot drift apart.
- A `Progress` protocol (`progress.py`) wired into `pipeline.write_archive`,
  `one_part`, the `write.py` chunk loop and the verify loop. The CLI's TTY
  progress lines are now one `Progress` implementation.
- GUI tests that run without a display: `tests/test_gui.py` drives the
  controller headlessly, and a `gui` pytest marker covers tests that need a
  real Tk window (deselected by default, run with `-m gui`).

### Changed

- Dependabot version updates for uv and GitHub Actions now run monthly, on
  the 22nd at 16:00 America/New_York, with a 7-day cooldown. Security updates
  are unaffected. The weekly dependency audit keeps its Thursday schedule.

- Every `uvx` call in `ci.yml` and `dependency-audit.yml` now passes
  `--no-build` and pins an exact version (`pip-audit==2.10.1`,
  `pre-commit==4.7.0`, `zizmor==1.31.0`). `--no-build` stops uv from falling
  back to an sdist build, which executes a package's PEP 517 backend at
  install time; the pins stop an unreviewed upstream release from reaching CI.
- ci.yml's audit job writes its requirements file to `$RUNNER_TEMP` instead of
  the shared `/tmp`.
- All three ci.yml jobs set `timeout-minutes`, which dependency-audit.yml
  already did. The 6-hour default let a hung `apt-get`, `brew` or PyPI call run
  until GitHub killed it.
- `pipeline.py`, `write.py` and the test helpers take `Options` instead of an
  `argparse.Namespace` (plan: `dev-docs/plans/2026-10-10-gui.md`).
- All four `.pre-commit-config.yaml` hook revs are pinned to commit SHAs (with
  the release tag kept as a comment), and two that had drifted are bumped
  (gitleaks v8.30.0 to v8.30.1, ruff-pre-commit v0.16.10 to v0.17.1). A tag can
  be moved; a SHA cannot (plan:
  `dev-docs/plans/archive/2026-10-15-sha-pin-ci-tooling.md`).
- All five `setup-uv` steps pin `version: "0.12.24"`. The input was unset, so
  every run resolved to `latest`.
- New `check-pins` policy hook: hook revs must be full SHAs (except
  `local`/`meta`) with tag comments, `setup-uv` steps must pin an exact
  `x.y.z` version, and remote `uses:` refs must pin full SHAs. It runs via
  `uv run python`, so PyYAML joins the `dev` group.
- `tests/test_check_pins.py`: 46 pytest cases covering the guard's fixture
  matrix (all three rules) plus quoted and multi-line `rev` layouts and
  case-varied `setup-uv` refs, so later edits cannot silently break it.

### Fixed

- `packaging/build.py` checks `--version` before it generates icons or runs
  PyInstaller, and it only publishes `dist/<version>/` after the freeze
  succeeds. A version with a slash, `..`, or a non-ASCII digit is rejected.
  A failed freeze deletes its partial tree instead of replacing a finished
  app. Moving the previous tree aside, or putting it back when the new tree
  cannot take its place, exits with `SystemExit` rather than a traceback.
  Removing the leftover `.previous` tree after a successful publish does not
  fail the build. The spec calls `resolved_data_files()`, so the paths
  PyInstaller receives are absolute.
- A Tk preflight with no display names `xvfb-run`. The Linux container is
  what provides that display; macOS and Windows do not need it.
- `gui_view.set_icon` keeps the `PhotoImage` on the window, so a PNG (or SVG)
  icon is still there after `set_icon` returns.
- Packaging icon tests live in `tests/test_packaging_icons.py`, so neither
  that file nor `tests/test_packaging.py` sits over the 600-line soft cap.
  The network-free icon test no longer fails on a host with no pinned resvg.
- `packaging/build.py` rejects a `--target` that is not the build machine.
  PyInstaller freezes the OS it runs on, so a mismatched target stopped
  before icon generation.
- Packaging tests that check a created file's mode keep the exact `0o600` and
  `0o755` bits on POSIX. On Windows they only require the file to be
  writable, because `chmod` there cannot set those bits.
- `packaging/icons.py` no longer accepts a path on the command line, and it
  no longer calls `urlopen` or `extractall`. Those were the Sonar security
  findings (a CLI path reached the unpack and `resvg`'s arguments) and the
  CodeFactor finding (an open URL with no scheme check). The download stays
  on https to GitHub's release hosts, and an archive contributes only its
  bare `resvg` or `resvg.exe` member.
- The basedpyright pre-commit hook runs `uv run --group build`, so the
  type check sees Pillow. A plain `uv sync` still omits the build group.
- `latest-deps.yml` syncs the `build` group before basedpyright. Both weekly
  Python jobs typecheck `packaging/`, which imports Pillow, and the
  typecheck step passes `--no-sync`, so it cannot install that group itself.
- `dependency-audit.yml` no longer prints advisory text unescaped. A newline in
  a GitHub advisory description used to end the `::error` annotation, and the
  rest of the text was parsed as runner commands.

## [0.1.0] - 2026-10-08

### Added

- Agent harness: `AGENTS.md`, `CLAUDE.md` pointer, `.gitignore`, `ruff.toml`.
- Pre-commit hooks: gitleaks, file hygiene, ruff, markdownlint, and the repo
  policy checks for file size, doc freshness and `TODO.md` size.
- `user-docs/` and `dev-docs/` folders, with plan lifecycle guidance in
  `dev-docs/README.md`.
- `TODO.md` for future work.

### Changed

- Applied the 2026-10-08 Grok 4.7 review to `SPEC.md` and the v1 plan:
  central-directory reservation in admission, explicit `ZIP_32`/`ZIP_64`,
  source-size checks, outer-layer overhead for `--hide-names`, rename only
  after every part verifies, and AE-2-only verification. Evidence is in
  `dev-docs/investigations/2026-10-08-stream-zip-spike.md`.
- Applied the 2026-10-08 Codex review to `SPEC.md` and the v1 plan: zlib's
  deflate bound, outer-layer bound, no-clobber publication with `--force`
  backups, source identity checks, Zip64 entry-count switch, structural
  verification, DOS-only timestamps, and `getpass` echo fallback.
- Applied the 2026-10-08 Muse Spark harness review: hooks match whole path
  segments, the freshness hook rejects malformed and future dates, the TODO
  hook checks only root `TODO.md`, a root `README.md`, and clearer
  `AGENTS.md` doc-update and test-password rules.
- Applied the 2026-10-08 re-reviews: a `--force` commit point, 64-bit
  methods for directories, full central-entry verification, two symlink
  traversal policies, `O_NONBLOCK` leaf opens, directory identity checks,
  and an empty-part pre-check. The TODO hook now checks `TODO.md` when run
  without arguments, and the freshness hook rejects trailing junk after the
  date.
- Phase 1 scaffold: `pyproject.toml` (uv, `src/` layout, `zipseal` console
  script), `errors.py`, `sizes.py`, `passwords.py`, the full argparse CLI,
  pytest markers, and a `basedpyright` pre-commit hook. 48 tests.
- Phase 2 collect: `collect.py` walks inputs through held directory
  descriptors with `os.fwalk`, records the identity chain of every entry,
  applies excludes, symlink policies, special-file skips, empty folders,
  NFC names, casefold collisions, timestamp clamping and output-in-input
  skipping. `--dry-run` lists entries. 66 tests.
- Phase 3 single archive: `plan.py` bounds (framing measured against
  stream-zip in tests), `sources.py` descriptor-based reads with identity
  checks, `write.py`, `verify.py`, `zipcheck.py` structural verification,
  and `output.py` no-clobber publication with `--force` backups. Fixed
  non-ASCII passwords, which stream-zip encodes as Latin-1. 110 tests.
- Phase 4 split: exact compressed-byte counting (design A, recorded in
  `dev-docs/investigations/2026-10-08-part-admission.md`), the §6.2
  admission rule, part rollover, `--order size` first-fit-decreasing, the
  empty-part pre-check, and a runtime check that predicted part sizes equal
  written sizes. `hypothesis` property test over random sizes and caps.
- Phase 5 safe writes: failure, interrupt, disk-full, `--force` rollback and
  commit-point tests. Source read errors now name the source file.
- Phase 6 and manifest: `plan.Layout` frames plain or nested parts; the
  outer layer is reserved with zlib's bound over the whole inner zip; both
  layers have exact runtime size accounting; verification decrypts the outer
  entry, streams the inner zip through `stream-unzip`, and parses its
  central directory from the retained tail. 147 tests.
- Phase 7 (partial): progress lines on a TTY, user docs (quick start, CLI
  reference, opening archives, security), root README, and slow tests for a
  file over 4 GiB and 10,000 small files.
- 7-Zip interop tests (`tests/test_sevenzip.py`), run against 7-Zip 26.04.
- Data hooks for publishing safely: forbidden tracked paths, protected `.gitignore` rules, and a home-path and email scan.
- MIT license. GitHub Actions CI: pre-commit hooks, tests on Linux and macOS with Python 3.11 and 3.13 (including 7-Zip and bsdtar interop), and a pip-audit dependency audit. Dependabot for uv and Actions.
- Applied the GLM 5.3 review of PR #1: see the plan's review log. 159 tests.
- Applied the kg-pr-review (DeepSeek) review of PR #1: the data hooks now fail closed outside a git repository, and only `noreply@anthropic.com` is allowlisted, not the whole domain.
- Applied the CodeRabbit review of PR #1: Actions pinned to commit SHAs (checkout v7.0.1, setup-uv v10.2.0), NUL-delimited `git ls-files` in the forbidden-paths hook, file-versus-folder collision detection, part numbers wide enough to sort past 999 parts, safer sample cleanup, and docs that no longer put the password on a `tar` command line.
- Applied the second CodeRabbit review: `persist-credentials: false` on every checkout, and the forbidden-paths hook decodes `git ls-files -z` output like the filesystem, so non-UTF-8 names are checked instead of crashing it.
