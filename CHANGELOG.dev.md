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
