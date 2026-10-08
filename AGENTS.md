# AGENTS.md

Single source of truth for AI coding agents in this repository. `CLAUDE.md` is a
thin pointer back here.

`zipseal` is a Python CLI that writes files and folders into AES-256 encrypted
zips. It can split output into self-contained parts that each stay under a size
cap. The design and the implementation plan both live in [`SPEC.md`](SPEC.md).

## Status

Nothing is implemented yet. Work follows the steps in `SPEC.md` §8, in order.
Resolve or record the open questions in §9 before the step they affect.

## Read this first

| If you are… | Read |
|---|---|
| Implementing a feature | `SPEC.md` §4–§6 for behavior, §8 for order and tests |
| Touching passwords, encryption, or file writes | `SPEC.md` §6.5–§6.7 and §7, then the security rules below |
| Resuming someone else's work | `.context/handoff.md`, if present |

## Commands

The project uses `uv`. These commands work once step 1 of the plan adds `pyproject.toml`.

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
SPEC.md               design and implementation plan
src/zipseal/          cli, collect, plan, write, verify (see SPEC.md §5)
tests/                pytest; fixtures are generated in tmp_path
hooks/scripts/        repo policy checks run by pre-commit
.context/             scratch plans and handoffs (gitignored)
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
- Error messages may name input files. They must never include file contents.

## Conventions

- Python 3.11+, `ruff` for lint and format (config in `ruff.toml`).
- Keep source files under 600 lines. `hooks/scripts/check_file_size.py` warns at
  600 and blocks at 1000.
- Every behavior in `SPEC.md` §8's test list gets a pytest test. Mark slow
  tests with `@pytest.mark.slow`. Skip `7zz` tests when the binary is missing.
- If code and `SPEC.md` disagree, fix one of them in the same change. Do not
  leave the spec stale.
- Record user-facing changes in `CHANGELOG.md` under `[Unreleased]`.
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
