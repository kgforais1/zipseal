# AGENTS.md

Last reviewed: 2026-10-08

Single source of truth for AI coding agents in this repository. `CLAUDE.md` is a
thin pointer back here.

`zipseal` is a Python CLI that writes files and folders into AES-256 encrypted
zips. It can split output into self-contained parts that each stay under a size
cap. The design lives in [`SPEC.md`](SPEC.md).

## Status

v1 is implemented on the `feat/v1` branch, following
[`dev-docs/plans/2026-10-08-v1-implementation.md`](dev-docs/plans/2026-10-08-v1-implementation.md).
The plan's unticked boxes list what remains: the manual Finder and Keka
check, and the `0.1.0` release.

## Read this first

| If you are… | Read |
|---|---|
| Implementing a feature | `SPEC.md` §4–§6 for behavior, then the active plan for order and tests |
| Touching passwords, encryption, or file writes | `SPEC.md` §6.5–§6.7 and §7, then the security rules below |
| Starting or finishing a plan, or logging done work | [`dev-docs/README.md`](dev-docs/README.md) |
| Picking the next task | [`TODO.md`](TODO.md) and the active plan in `dev-docs/plans/` |
| Resuming someone else's work | `.context/handoff.md`, if present |

## Commands

The project uses `uv`.

```sh
uv sync                        # install dependencies
uv run zipseal --help          # run the CLI
uv run pytest                  # fast tests
uv run pytest -m slow          # Zip64 / 4 GiB tests
pre-commit run --all-files     # lint, format, secret scan, file-size policy
```

Run `pre-commit install` once per clone to enable the git hook.

## Layout

```
SPEC.md               design; the source of truth for behavior
TODO.md               future work only; never records finished work
CHANGELOG.md          finished user-visible work
CHANGELOG.dev.md      finished internal work (harness, hooks, CI, tests)
src/zipseal/          cli, collect, plan, sources, write, verify, zipcheck, output, pipeline
tests/                pytest; fixtures are generated in tmp_path
user-docs/            docs for people who run zipseal or open its archives
dev-docs/plans/       active plans; finished ones move to plans/archive/
dev-docs/investigations/  dated research and spike write-ups
hooks/scripts/        repo policy checks run by pre-commit
.context/             scratch and handoffs (gitignored)
sample-data/          local inputs for manual runs (gitignored)
```

## Security rules

These rules are the point of the tool. Treat a violation as a bug.

- Never default to ZipCrypto. AES-256 (WinZip AE-2) is the only default.
- Never put a password in argv, logs, exceptions, progress output, or test
  output. `--generate-password` prints it once, to stderr only.
- Never write plaintext to disk. That includes temp files, the `--hide-names`
  inner zip, and debug dumps.
- Write parts as `.partial`, verify, then rename. Delete every `.partial` on
  failure. Create outputs with mode `0600`.
- Never commit real input data or generated archives. `.gitignore` blocks
  `*.zip`, `*.partial` and volume files. Tests build their inputs in `tmp_path`.
  For manual runs, put inputs in `sample-data/` (gitignored).
- Test passwords must be obviously fake, such as `test-password`. If gitleaks
  flags a fixture anyway, add a `# gitleaks:allow` comment on that line, and
  say why in the commit message. Never allowlist a whole folder.
- Error messages may name input files. They must never include file contents.

## Conventions

- Python 3.11+, `ruff` for lint and format (config in `ruff.toml`).
- Keep source files under 600 lines. `hooks/scripts/check_file_size.py` warns at
  600 and blocks at 1000.
- Every behavior in the plan's test list gets a pytest test. Mark slow
  tests with `@pytest.mark.slow`. Skip `7zz` tests when the binary is missing.
- If code and `SPEC.md` disagree, fix one of them in the same change. Do not
  leave the spec stale.
- Follow the plan lifecycle and doc gardening rules in
  [`dev-docs/README.md`](dev-docs/README.md). In short: tick a plan box only
  when the task is verified, archive finished plans, delete finished items
  from `TODO.md`, and log the work in `CHANGELOG.md` (user-visible) or
  `CHANGELOG.dev.md` (internal).
- When behavior changes, update whichever of `SPEC.md`, `AGENTS.md` and
  `user-docs/` describes it, in the same commit.
- Use Conventional Commit prefixes (`feat:`, `fix:`, `docs:`, `chore:`, `test:`).

## Agent tooling policy

- Search and read targeted files before requesting broad repository context.
- Use one primary code-intelligence/indexing tool per role or task.
- Prefer a CLI plus task-specific skill for batch work; use MCP when persistent,
  interactive state materially helps.
- Record decisions, changed files, verification, and next steps in
  `.context/handoff.md` before changing agents or IDEs.
- Keep credentials, generated indexes, and local agent state (`.agent-state/`)
  out of version control.
