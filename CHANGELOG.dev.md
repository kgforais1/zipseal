# Developer changelog

Internal changes that users cannot see: harness, hooks, CI, tests, docs-only
edits and refactors. User-visible changes go in [`CHANGELOG.md`](CHANGELOG.md).

## [Unreleased]

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
