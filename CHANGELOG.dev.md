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
