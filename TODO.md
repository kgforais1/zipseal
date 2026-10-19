# TODO

Last reviewed: 2026-10-10

Future work only. Each item is something nobody has started or finished.

When an item is done, delete it from this file in the same commit. Log the
work in `CHANGELOG.md` if users can see it, or in `CHANGELOG.dev.md` if they
cannot. Never mark items `[x]` here, and never keep a "done" section.

An item that needs more than a few lines of thought gets a plan in
`dev-docs/plans/`. Link it from the item.

## Next

- Nothing scheduled. Pick from Later.

## Later

- Move the CI-only tools (`pip-audit`, `pre-commit`, `zizmor`) out of inline
  workflow pins and into a `[dependency-groups]` entry in `pyproject.toml`,
  locked in `uv.lock` and run with `uv run --group ci --locked`. That buys
  hash verification and Dependabot-driven bumps, which the inline `==` pins in
  `.github/workflows/` do not get (Dependabot's `github-actions` ecosystem
  updates `uses:` references, not versions inside `run:` steps). Costs a
  `uv.lock` diff and puts CI tooling in the app's dependency closure.
- Let a GUI cancel land while a part is being verified. Today `verify_part`
  reports no progress until the whole part is decrypted, so a cancel waits for
  it. It needs a progress or cancel hook inside verification.
- Add drag-and-drop to the GUI via `tkinterdnd2` ([GUI plan](dev-docs/plans/2026-10-10-gui.md)).
- Package the GUI as a signed, double-clickable macOS `.app` with PyInstaller or Briefcase ([GUI plan](dev-docs/plans/2026-10-10-gui.md)).
- Consider `--format 7z`, `--oversize=volumes` and `--tight` (`SPEC.md` §6.2, §6.4, §6.7).
