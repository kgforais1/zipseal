# Plan: GUI executables for macOS, Windows and Linux

Date: 2026-11-02
Status: draft
Linked: TODO.md "GUI executables for macOS, Windows and Linux"; supersedes the
macOS-only `.app` bullet in `dev-docs/plans/2026-10-10-gui.md` ("Later")

## Goal

Ship `zipseal-gui` as a downloadable app for macOS, Windows and Linux that needs
no Python, no `uv` and no terminal. These are the only executables this project
builds: the CLI stays a GitHub project for `uv tool install` (Phase 6 adds PyPI,
which is a package, not a binary).

| Platform | Artifact | Install |
|---|---|---|
| macOS (arm64 first) | `zipseal-<version>-macos-arm64.dmg`, containing `zipseal.app`, signed (Developer ID) and notarized | drag `zipseal.app` to Applications |
| Windows (x64) | `zipseal-gui-<version>-windows-x64.zip` (PyInstaller onedir) | unzip anywhere, run `zipseal-gui.exe` |
| Linux (x86_64) | `zipseal-gui-<version>-linux-x86_64.AppImage`, plus a `.tar.gz` of the onedir | `chmod +x` and run (tar.gz runs from any folder) |

Every artifact is built and smoke-tested in CI from the tagged commit, attached
to a GitHub Release together with `SHA256SUMS` and a build provenance
attestation, and accepted on a machine without Python before the release is
published. A smoke-tested artifact, never a second local build, is what ships.

## Non-goals

- No CLI executables.
- No auto-update, no settings, no phone-home. The window's "keeps nothing"
  behavior stays true in the frozen app.
- No macOS App Sandbox, no Mac App Store, no Microsoft Store *commitment* (a
  Store spike is Phase 2 because it is the only free route to zero SmartScreen
  warnings).
- No iOS, Android or web.
- No reproducible-build guarantee. Integrity comes from `SHA256SUMS`, GitHub
  attestations and, on macOS, the notarized signature.
- Drag-and-drop and the remaining GUI-plan "Later" items stay separate work.

## Decisions

1. **Freezer: PyInstaller** (pinned in a build dependency group). It handles
   Tcl/Tk on all three targets, can codesign `.app` bundles
   (`--codesign-identity`, hardened runtime) and produces both `onedir` and
   `onefile`; `onedir` is chosen to keep AV false positives rare (a known
   `onefile` problem) and startup fast. **Briefcase is rejected**: its Windows
   backend uses the python.org Windows Embeddable package, which has no
   `tkinter` ("Tkinter is not available", briefcase docs, checked 2026-11-02) —
   a hard blocker for this GUI. Nuitka is rejected: no need for compilation,
   slower Python-version support. PyInstaller 6.22.3 (2026-09-12) supports
   Python 3.11–3.15 and bundles `ldd`-era glibc floors of 2.17 on Linux.
2. **Build Python: uv-managed python-build-standalone**, the same family the
   `zipseal-gui.command` launcher already uses, because Tk is present on every
   platform and PyInstaller compatibility with its dynamically linked
   `_tkinter`/`libtcl`/`libtk` landed in 2025. The build script pins the Python
   minor; the resolved version and Tk version go in the release notes. Start on
   the version CI tests (today 3.13) and revisit 3.14 for Tk 9 on Windows if the
   window icon is judged to matter (Decision 7).
3. **Windows signing: do not buy Azure Artifact Signing.** Microsoft's current
   docs (2026-08-29) say it costs $9.99/month *and* gives no instant
   SmartScreen trust — reputation builds over time; individual developers are
   limited to the USA/Canada. EV certificates stopped bypassing SmartScreen in
   2024, so the premium is pointless. The free routes, in order:
   - **SignPath Foundation**: free OV-level signing for qualifying OSS
     projects (SignPath's certificate and HSM; publisher shows as "SignPath
     Foundation"). Requires a released, documented project (v0.1.0 counts by
     intent — ask; the acceptance letter decides), a "Code signing policy"
     section on the README with their exact wording and role list, and their
     GitHub Actions integration with per-release approvals.
   - **Microsoft Store (MSIX)**: individual registration is free since
     September 2025, and Store MSIX packages are re-signed by Microsoft, which
     is the only recorded way to get zero SmartScreen warnings. Needs a spike
     for a full-trust Win32 app.
   Until one lands, the zip ships unsigned with documented SmartScreen steps and
   a note that Windows 11 Smart App Control may block unsigned apps outright.
   No calendar cost, only the documentation debt.
4. **macOS: Developer ID + notarization** (the Apple Developer account is
   already available). Sign the `.app` with hardened runtime and a secure
   timestamp, notarize with `notarytool` using an App Store Connect API key,
   staple the `.app` and the DMG, and gate CI on `codesign --verify --deep
   --strict`, `spctl --assess -t exec` and `stapler validate`. Entitlements
   start empty; add only what notarization or launch demonstrably needs, and
   record why here.
5. **Nothing build-output is ever committed.** `dist/` and `build/` are already
   in `.gitignore`; extend both `.gitignore` and `.forbidden-paths` with the
   artifact globs (`*.dmg`, `*.msi`, `*.exe`, `*.AppImage`) so even a
   force-added artifact cannot be committed.
6. **Release mechanics**: tag `vX.Y.Z` → `release.yml` builds on a pinned
   runner image per platform → smoke tests the built artifact → writes
   `SHA256SUMS` → attests each artifact (`actions/attest-build-provenance`
   v4.x; public repo, so free) → creates a **draft** GitHub Release. The
   maintainer publishes it after the manual acceptance checks below.
7. **Icons are generated at build time from `src/zipseal/icon.svg`**
   (nothing raster enters the repo; `*.png` is blocked by design). macOS needs
   an `.icns`, Windows an `.ico` for the exe plus a window icon, Linux a
   `.desktop` icon. A pinned rasterizer (`resvg` static binary, or platform
   tools) does the conversion in the build script. The app's
   `gui_view.set_icon` already prefers Tk 9's SVG reader; where a bundle
   carries Tk 8.6, add a PNG fallback generated at build time so the window and
   taskbar still get the zipseal icon.
8. **macOS architecture (proposed, needs your sign-off)**: ship arm64 first.
   Universal2 is not viable — PyInstaller only emits it when every bundled
   wheel is universal2, and python-build-standalone has no universal2 builds.
   An Intel leg would run on `macos-15-intel`, the last x86_64 image, which
   GitHub stops supporting in Fall 2027 (`macos-13` was retired 2025-12-04).
   Recommend: no Intel build; Intel Macs keep the source install. Revisit only
   if someone asks.
9. **One version.** `pyproject.toml` stays the single source of truth; the
   build script substitutes it into `Info.plist`, the Windows version resource
   and artifact names, and the release workflow fails unless the tag equals it.
10. **The CLI package stays source-installable** (`uv tool install git+…`).
    PyPI is Phase 6: the name `zipseal` is unclaimed there (checked
    2026-11-02), and Trusted Publishing means no tokens.

## Phase 0 — Packaging plumbing

- [ ] Audit the GUI's frozen-run assumptions. Today the only file reference is
      `gui.ICON = Path(__file__).with_name("icon.svg")` (`gui.py:168`), loaded
      by `gui_view.set_icon` with Tk's SVG reader. The spec must collect
      `src/zipseal/icon.svg` into the bundle next to the module, and a smoke
      check must confirm it exists in the frozen tree. No cwd or `__file__` use
      elsewhere.
- [ ] Add a `build` dependency group to `pyproject.toml`
      (`pyinstaller==6.22.3` first entry; locks into `uv.lock`, Dependabot
      bumps it). Builds run as `uv run --group build`.
- [ ] Extend `.gitignore` and `.forbidden-paths` with `*.dmg`, `*.msi`,
      `*.exe`, `*.AppImage`; confirm `dist/` and `build/` are in both files'
      spirit (already ignored; add to `.forbidden-paths`).
- [ ] Create `packaging/`:
  - `build.py` — one entry point:
    `uv run --group build python packaging/build.py --target {macos,windows,linux}`
    with `--skip-sign` for local runs and `--version` defaulting to
    `pyproject.toml`. Outputs under `dist/<version>/`.
  - `zipseal-gui.spec` — onedir, windowed, `name="zipseal-gui"`, macOS BUNDLE
    `zipseal.app`, bundle id, version substitution, `datas` (the SVG), and
    `excludes` (`pytest`, `hypothesis`, `basedpyright`, `yaml`, `PIL` if unused).
  - `macos/entitlements.plist` — empty `<dict>` to start.
  - `windows/version_info.txt` template.
  - `linux/zipseal-gui.desktop` and `linux/AppRun` for the AppImage.
  - `icons.py` — SVG to `.icns`/`.ico`/`.png` at build time; pinned tool.
- [ ] `tests/test_packaging.py` covering the test list below.
- [ ] `AGENTS.md` command for a local build; `dev-docs/README.md` unchanged.

## Phase 1 — macOS app (milestone M1)

- [ ] Build a local unsigned `zipseal.app`; open it from `dist/` and run a real
      archive end to end (same inputs as the GUI plan smoke test).
- [ ] `Info.plist`: `CFBundleShortVersionString`/`CFBundleVersion` from
      `pyproject.toml`, a reverse-DNS `CFBundleIdentifier` derived from the
      GitHub owner (record the exact id when implementing),
      `CFBundleName`/`CFBundleDisplayName` `zipseal`, `CFBundleIconFile`,
      `NSHighResolutionCapable`, and `LSMinimumSystemVersion` set from what the
      bundled Python actually supports — verify on the oldest macOS you can,
      do not guess the floor.
- [ ] Make the DMG: `hdiutil create -format UDZO`, `zipseal.app` plus an
      Applications symlink (drag-install).
- [ ] CI signing path: import the Developer ID certificate from secrets into a
      temporary keychain, sign via the spec's `codesign_identity` +
      entitlements, verify with `codesign --verify --deep --strict`.
- [ ] Notarization path: `xcrun notarytool submit --wait` with the App Store
      Connect API key; staple the `.app`, then build, sign (`codesign`) and
      notarize the DMG, then staple the DMG. Gate on `spctl --assess -t exec`
      (expect "Notarized Developer ID") and `stapler validate`.
- [ ] CI smoke: launch the app's inner binary, wait, confirm it is alive,
      terminate. Mark advisory if the runner proves flaky; the real gate is the
      manual acceptance below.
- [ ] Manual acceptance: download the drafted release asset fresh (quarantine
      flag set), open the DMG, drag to Applications, launch, create an archive
      with a generated password, open it in Finder and 7-Zip. Record the date
      and macOS version here.

## Phase 2 — Windows app

- [ ] Build the onedir zip on `windows-latest` with the uv-managed Python;
      embed the exe icon and the file version resource.
- [ ] CI smoke: start `zipseal-gui.exe`, wait, confirm it is alive, stop it.
- [ ] Resolve signing (Decision 3), in this order:
  - SignPath Foundation application: add the required "Code signing policy"
    section to `README.md` with their exact wording
    ("Free code signing provided by SignPath.io, certificate by SignPath
    Foundation"), list committer/approver roles, then apply with the repository
    and download URLs. If approved, integrate their GitHub Action, pin it by
    SHA, and keep per-release approvals in mind.
  - Store MSIX spike: free individual Partner Center account, package the
    onedir as a full-trust MSIX, submit once, confirm Microsoft re-signing
    removes SmartScreen warnings. Decision after the spike; do not commit to
    the Store before it passes certification once.
  - Until signed: document "More info → Run anyway", note Smart App Control on
    Windows 11 may block unsigned apps, and submit any AV false positive to
    Microsoft's portal.
- [ ] Optional, deferred until asked: Inno Setup installer (the portable zip is
      the artifact this plan promises) and a winget manifest PR.

## Phase 3 — Linux app

- [ ] Build inside a pinned `ubuntu:22.04` container for a glibc 2.35 floor
      (PyInstaller bootloader itself is glibc 2.17+), onedir, then AppImage via
      a pinned `appimagetool`; also produce the `.tar.gz`.
- [ ] AppDir contents: `zipseal-gui.desktop` (`Terminal=false`,
      `Categories=Utility;Security;`), `AppRun`, generated icon.
- [ ] CI smoke under `xvfb-run`: launch, wait, assert the process is alive, and
      if practical assert a window named `zipseal` exists
      (`xdotool search --name`), then terminate.
- [ ] Docs: `chmod +x`, the FUSE fallback
      (`./zipseal-gui.AppImage --appimage-extract-and-run`), and that the
      `.tar.gz` runs from any folder.

## Phase 4 — Release workflow

- [ ] `.github/workflows/release.yml`: `on: push: tags: ["v*"]`; jobs `check`
      (tag equals `pyproject.toml` version; fast suite passes), `build-macos`,
      `build-windows`, `build-linux`, `publish`.
- [ ] Every action pinned by full SHA with a tag comment (the `check-pins` hook
      enforces it); minimal top-level `permissions:`; `contents: write` only in
      `publish`; `id-token: write` + `attestations: write` for provenance.
- [ ] Publish job: collect artifacts, write `SHA256SUMS` (sha256 over every
      artifact), attest each artifact and the sums with
      `actions/attest-build-provenance`, then
      `gh release create vX.Y.Z --draft --title … --notes …` attaching
      everything. Release notes include the resolved Python, PyInstaller
      version, runner image, glibc floor and Tk version per artifact, plus the
      `SHA256SUMS` verification line and the `gh attestation verify` line.
- [ ] `dev-docs/releasing.md` (new durable doc): the tag-to-release runbook,
      the secrets list (names only), rollback (delete draft → delete tag → fix
      → re-tag), and the acceptance checklist from Phases 1–3.
- [ ] First real run at the next version bump; v0.1.0 stays source-only.

## Phase 5 — Docs

- [ ] `README.md` Install: a downloads table (macOS / Windows / Linux) and keep
      `uv tool install` for the CLI.
- [ ] `user-docs/gui.md` "Start it" → "Get the app": per-OS first-run notes
      (macOS: nothing to do; Windows: SmartScreen; Linux: chmod +x).
- [ ] New `user-docs/troubleshooting-app.md` (or a section): SmartScreen, Smart
      App Control, AV false positives, AppImage FUSE, "where does it write?".
- [ ] `AGENTS.md`: build command, `packaging/` in the layout, release workflow.
- [ ] `SPEC.md`: the packaging line (around line 106) becomes the artifact
      table above; note the GUI ships frozen while the CLI stays source.
- [ ] `CHANGELOG.md` (user-visible) and `CHANGELOG.dev.md` (workflow internals);
      doc-gardening pass; bump `Last reviewed` dates after re-reading.

## Phase 6 — CLI on PyPI (optional, decide after M3)

- [ ] `uv build` and publish via PyPI Trusted Publishing from the release
      workflow (`id-token: write`, `pypi` environment). Name `zipseal` is free
      (checked 2026-11-02).
- [ ] README: `uvx zipseal` as the one-line CLI install.
- [ ] Only worth doing if installing the CLI without a git URL is wanted; it
      changes nothing for GUI users.

## Test list

Each behavior gets a pytest test per repo convention. Packaging tests:

- [ ] `read_version()` returns `pyproject.toml`'s version; a version
      substitution render (Info.plist fields, Windows version resource string)
      contains it.
- [ ] The artifact globs (`*.dmg`, `*.msi`, `*.exe`, `*.AppImage`) are present
      in `.forbidden-paths` and the output roots (`dist/`, `build/`) are
      ignored by `.gitignore`; a synthetic untracked artifact under `dist/`
      fails the forbidden-paths hook when tracked.
- [ ] `packaging/linux/zipseal-gui.desktop` has `Name`, `Exec`, `Icon`,
      `Terminal=false`, sorted `Categories`; `AppRun` is tracked executable.
- [ ] `packaging/macos/entitlements.plist` parses with `plistlib` and is an
      empty dict until a documented change.
- [ ] `collect_data_files()` includes `src/zipseal/icon.svg` (the freeze-time
      icon dependency), matching `gui.ICON`'s source path.
- [ ] If the PNG fallback lands: `tests/test_window_icon.py` gains a case for
      "SVG raises TclError, PNG present, icon set from PNG", and "neither
      present, returns False and the launch is unaffected".

CI smoke gates (not pytest): the per-platform launch checks in Phases 1–3 run
against the artifact the workflow uploads, and the macOS job additionally gates
on `codesign`/`spctl`/`stapler`. The manual acceptance in Phases 1–3 is recorded
in this plan with a date.

## Secrets to set up (names only)

`APPLE_CERT_P12` (base64 Developer ID Application .p12), `APPLE_CERT_PASSWORD`,
`APPLE_TEAM_ID`, `APPLE_API_KEY_ID`, `APPLE_API_ISSUER_ID`,
`APPLE_API_PRIVATE_KEY` (base64 .p8), `KEYCHAIN_PASSWORD` (ephemeral chain).
`SIGNPATH_*` only if Phase 2 signing is approved. Linux needs no secrets.
`dev-docs/releasing.md` documents where each comes from and how to rotate it.

## Risks and open questions

1. **SignPath acceptance is not guaranteed** (project must be "released",
   documented, OSI-licensed, and it needs a code-signing policy page and
   approver roles). If declined: stay unsigned with documentation, or pursue
   the Store spike. Neither path costs money, which is the point of Decision 3.
2. **Store MSIX effort is unknown** for a PyInstaller onedir app (full-trust
   packaging, Store certification). The spike is deliberately time-boxed.
3. **Notarization surprises**: first submission may need an entitlement tweak
   (Tk/PyInstaller). Budget a few iterations; every future release must stay
   signed and stapled or user trust breaks.
4. **AV false positives** are a PyInstaller reality; onedir reduces them, and
   consistent signing helps reputation. Respond to reports via Microsoft's
   portal; document known reports in the troubleshooting page.
5. **Intel macOS**: no build proposed (Decision 8); GitHub ends x86_64 macOS
   runners in Fall 2027 regardless.
6. **Tk version per platform** decides the window icon (cosmetic; the file icon
   is separate). Verified per artifact and recorded in the release notes.
7. **Size**: expect roughly 15–40 MB per artifact. If that matters, revisit
   `excludes` — not a gate.
8. **Run-time floors** (macOS minimum, glibc, Windows version) come from the
   bundled Python, not from Python's docs; measure and document the real ones.
9. **Open question for the user**: macOS arm64 only, or add the Intel leg?
   (Decision 8 proposes arm64 only.)

## Milestones

- **M1**: local macOS `zipseal.app` runs from `dist/`, does a real archive;
  Phase 0 tests green. No CI yet.
- **M2**: tagged workflow produces a signed, notarized, stapled DMG as a draft
  release; manual acceptance recorded; maintainer publishes.
- **M3**: Windows zip and Linux AppImage + tar.gz join the same workflow,
  smoke-tested in CI, `SHA256SUMS` + attestations attached; Windows signing
  resolved one way or the other.
- **M4**: README, `user-docs/`, `AGENTS.md` and `SPEC.md` updated;
  `dev-docs/releasing.md` written; PyPI decision recorded.

## Review changes

(empty until review)
