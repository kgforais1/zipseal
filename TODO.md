# TODO

Last reviewed: 2026-11-03

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
- Ship `zipseal-gui` as downloadable apps for macOS (signed and notarized
  `.app` in a DMG), Windows (zip) and Linux (AppImage and a `.tar.gz` of the
  onedir), built and smoke-tested in CI from a tag and published as GitHub
  Releases. The CLI remains source-installable from GitHub with
  `uv tool install`.
  ([executables plan](dev-docs/plans/2026-11-02-gui-executables.md)).
- Ship Linux arm64 and Windows arm64 GUI executables once someone asks —
  deferred as non-goals in the
  [executables plan](dev-docs/plans/2026-11-02-gui-executables.md), where the
  research already exists: free `ubuntu-24.04-arm` and `windows-11-arm` runners
  for public repos, PyInstaller aarch64 Linux wheels and native Windows-arm64
  support. Do Linux arm64 first (no emulated fallback — x86_64 artifacts do not
  run there; start with the `.tar.gz` because aarch64 AppImage tooling is thin).
  Windows on ARM already runs the x64 zip via Prism emulation; a native build
  mainly needs a check that the arm64 python-build-standalone ships Tcl/Tk.
  Manual acceptance is possible with Windows 11 ARM under Parallels on the
  Apple Silicon Mac.
- Consider `--format 7z`, `--oversize=volumes` and `--tight` (`SPEC.md` §6.2, §6.4, §6.7).
