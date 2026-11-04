# Plan: GUI executables for macOS, Windows and Linux

Date: 2026-11-02
Status: draft
Linked: TODO.md "GUI executables for macOS, Windows and Linux"; supersedes the
macOS-only `.app` bullet in `dev-docs/plans/2026-10-10-gui.md` ("Later")

## Goal

Ship `zipseal-gui` as a downloadable app for macOS, Windows and Linux that needs
no Python, no `uv` and no terminal. These are the only executables this project
builds: the CLI remains source-installable from GitHub with `uv tool install`
(Phase 6 adds PyPI, which is a package, not a binary).

| Platform | Artifact | Install |
|---|---|---|
| macOS (Apple silicon) | `zipseal-gui-<version>-macos-arm64.dmg`, containing `zipseal-gui.app`, signed (Developer ID) and notarized | drag `zipseal-gui.app` to Applications |
| Windows (x64) | `zipseal-gui-<version>-windows-x64.zip` (PyInstaller onedir) | unzip anywhere, run `zipseal-gui.exe` |
| Linux (x86_64) | `zipseal-gui-<version>-linux-x86_64.AppImage`, plus a `.tar.gz` of the onedir | `chmod +x` and run (tar.gz runs from any folder) |

Every artifact is built in CI from the tagged commit and attached to a GitHub
Release together with `SHA256SUMS` and a build provenance attestation. CI
smoke launches that same artifact: Windows and Linux fail the job if the
process does not stay alive, and the macOS launch check may be marked
advisory when the headless runner is flaky. `codesign`, `spctl` and `stapler`
still fail the macOS job, and the manual acceptance below is the blocking
gate on every platform. Before the release is published, the drafted artifact
for macOS, Windows and Linux is accepted on a machine without Python: launch
it, create an archive with a generated password, and open that archive. The
artifact that was smoke-tested is what ships, never a second local build.

## Non-goals

- No CLI executables.
- No auto-update, no settings, no phone-home. The window's "keeps nothing"
  behavior stays true in the frozen app.
- No macOS App Sandbox, no Mac App Store, no Microsoft Store *commitment* (a
  Store spike is Phase 3 because it is the only free route to zero SmartScreen
  warnings).
- No iOS, Android or web.
- No Linux arm64 or Windows arm64 build in this plan: both are cheap to add
  later (free arm64 runners for public repos; PyInstaller ships aarch64 Linux
  wheels and native Windows-arm64 support) and are tracked in `TODO.md`.
  Windows on ARM already runs the x64 zip through Prism emulation; Linux arm64
  has no emulated fallback, so it is the first candidate if anyone asks.
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
   Python 3.11–3.15. On Linux its bootloader is built for glibc 2.17. That is
   the bootloader floor only. The application floor is measured from the
   bundled Python, Tcl/Tk and extension modules (Phase 4, Risk 8), and that
   measured value is what the release notes and user docs publish.
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
   2024, so the premium is pointless. Both free routes are pursued:
   - **SignPath Foundation**: free OV-level signing for qualifying OSS
     projects (SignPath's certificate and HSM; publisher shows as "SignPath
     Foundation"). Apply with the repository and download URLs, add the required
     "Code signing policy" section to `README.md` with their exact wording and
     role list, then integrate their GitHub Action (pinned by SHA) with
     per-release approvals.
   - **Microsoft Store (MSIX)**: individual registration is free since
     September 2025, and Store MSIX packages are re-signed by Microsoft — the
     only recorded way to get zero SmartScreen warnings. Run a time-boxed spike:
     package the onedir app as a full-trust MSIX, submit once, confirm Microsoft
     re-signing removes SmartScreen warnings. Decision after the spike passes
     certification once; do not commit to the Store before that.
   - **In parallel until one lands**: the zip ships unsigned with documented
     "More info → Run anyway" steps and a note that Windows 11 Smart App Control
     may block unsigned apps outright. No calendar cost, only documentation debt.
4. **macOS: Developer ID + notarization** (the Apple Developer account is
   already available). Sign the `.app` with hardened runtime and a secure
   timestamp, notarize with `notarytool` using an App Store Connect API key,
   staple the `.app` and the DMG, and gate CI on `codesign --verify --deep
   --strict`, `spctl --assess -t exec -v` and `stapler validate`. Pre-populate
   `packaging/macos/entitlements.plist` with
   `com.apple.security.cs.allow-unsigned-executable-memory` and
   `com.apple.security.cs.disable-library-validation` — the documented fix for
   W^X and loader failures under Hardened Runtime (`--options runtime`), which
   bite some CPython/libffi builds. Keep both for the first signed build,
   then verify empirically: the signed app must launch and notarize. If either
   entitlement is provably unneeded, remove it and record why here (Risk 3
   expects entitlement iteration).
5. **Nothing build-output is ever committed.** `dist/` and `build/` are already
   in `.gitignore`; extend both `.gitignore` and `.forbidden-paths` with the
   artifact globs (`*.dmg`, `*.msi`, `*.exe`, `*.AppImage`, `*.tar.gz`) so even a
   force-added artifact cannot be committed.
6. **Release mechanics**: tag `vX.Y.Z` → `release.yml` builds on a pinned
   runner image per platform → smoke tests the built artifact → writes
   `SHA256SUMS` → attests each artifact (`actions/attest-build-provenance`
   v4.x; public repo, so free) → creates a **draft** GitHub Release. The
   maintainer publishes it after the manual acceptance checks below.
   `release.yml` also runs on `workflow_dispatch` (no inputs) to rehearse
   the build and smoke test without drafting a release.
7. **Icons are generated at build time from `src/zipseal/icon.svg`**
   (nothing raster enters the repo; `*.png` is blocked by design). macOS needs
   an `.icns`, Windows an `.ico` for the exe plus a window icon, Linux a
   `.desktop` icon. A pinned rasterizer (`resvg` static binary, or platform
   tools) does the conversion in the build script. The app's
   `gui_view.set_icon` already prefers Tk 9's SVG reader; where a bundle
   carries Tk 8.6, add a PNG fallback generated at build time so the window and
   taskbar still get the zipseal icon.
8. **macOS architecture**: ship Apple silicon (arm64) only. Universal2 is not
   viable — PyInstaller only emits it when every bundled wheel is universal2,
   and python-build-standalone has no universal2 builds. No Intel build: Intel
   Macs keep the source install, and GitHub stops supporting x86_64 macOS
   runners entirely in Fall 2027 anyway. Revisit Intel only if someone asks.
9. **One version.** `pyproject.toml` stays the single source of truth; the
   build script substitutes it into `Info.plist`, the Windows version resource
   and artifact names. On a tag push, the release workflow fails unless the
   tag equals `v` plus that version and nothing else (`v0.1.0` when the
   project version is `0.1.0`). Compare the whole tag; do not strip a prefix.
   `lstrip("v")` would turn `vv0.1.0` into `0.1.0` and accept it, and
   `removeprefix("v")` leaves a tag that never had the prefix unchanged, so
   either check can accept a tag the rule rejects. On a `workflow_dispatch`
   rehearsal there is no release tag, so this check is skipped and the build
   uses the version in `pyproject.toml`.
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
- [ ] Extend `.gitignore` and `.forbidden-paths` with the artifact globs
      (`*.dmg`, `*.msi`, `*.exe`, `*.AppImage`, `*.tar.gz`) so even a
      force-added artifact cannot be committed; confirm `dist/` and `build/`
      are in both files' spirit (already ignored; add to `.forbidden-paths`).
- [ ] Create `packaging/`:
  - `run_gui.py` — the PyInstaller entry point: `import sys; from zipseal.gui import main; sys.exit(main())`.
    Neither `gui.py` nor `gui_view.py` has an `if __name__ == "__main__"` block, so this thin script
    is what the `.spec` targets.
  - `build.py` — one entry point:
    `uv run --group build python packaging/build.py --target {macos,windows,linux}`
    with `--skip-sign` for local runs and `--version` defaulting to
    `pyproject.toml`. Outputs under `dist/<version>/`.
  - `zipseal-gui.spec` — onedir, windowed, entry point `run_gui.py`,
    `name="zipseal-gui"`, macOS BUNDLE `zipseal-gui.app`, bundle id, version
    substitution, `datas` (the SVG), and `excludes` (`pytest`, `hypothesis`,
    `basedpyright`, `yaml`, `PIL` if unused).
  - `macos/entitlements.plist` — pre-populated with
      `com.apple.security.cs.allow-unsigned-executable-memory` and
      `com.apple.security.cs.disable-library-validation` (Decision 4's
      documented Hardened-Runtime fix; verify on the first signed build and
      trim only per Decision 4).
  - `windows/version_info.txt` template.
  - `linux/zipseal-gui.desktop` and `linux/AppRun` for the AppImage.
  - `icons.py` — SVG to `.icns`/`.ico`/`.png` at build time; pinned tool.
      Generated rasters are written to `build/icons/` (never `src/`, since
      `*.png` is blocked by `.forbidden-paths`), and PyInstaller bundles them
      via `datas`.
- [ ] `tests/test_packaging.py` covering the test list below.
- [ ] `AGENTS.md` command for a local build; `dev-docs/README.md` unchanged.

## Phase 1 — macOS app (milestone M1)

- [ ] Build a local unsigned `zipseal-gui.app`; open it from `dist/<version>/`
      and run a real archive end to end (same inputs as the GUI plan smoke
      test).
- [ ] `Info.plist`: `CFBundleShortVersionString`/`CFBundleVersion` from
      `pyproject.toml`, a reverse-DNS `CFBundleIdentifier` derived from the
      GitHub owner (record the exact id when implementing),
      `CFBundleName`/`CFBundleDisplayName` `zipseal`, `CFBundleIconFile`,
      `NSHighResolutionCapable`, `LSApplicationCategoryType`
      (`public.app-category.utilities`), `NSHumanReadableCopyright`, and
      `LSMinimumSystemVersion` set from what the bundled Python actually
      supports — verify on the oldest macOS you can, do not guess the floor.
- [ ] Make the DMG: `hdiutil create -format UDZO`, `zipseal-gui.app` plus an
      Applications symlink (drag-install).
- [ ] Manual acceptance (local build — M1 has no CI): set a synthetic
      `com.apple.quarantine` xattr on `zipseal-gui.app` so the Gatekeeper path
      is exercised, open the DMG, drag to Applications, launch, create an
      archive with a generated password, open it in Finder and 7-Zip. Record
      the date and macOS version here. The download-from-the-draft-release
      variant runs from M2 on (the last bullet of Phase 2).

## Phase 2 — macOS signing, notarization & release pipeline (milestone M2)

- [ ] CI signing path: import the Developer ID certificate from secrets into a
      temporary keychain, then unlock it for codesign with `security
      set-key-partition-list -S apple-tool:,apple:,codesign: -s -k
      "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"` (without this, `codesign` pops
      up a GUI prompt in headless CI and hangs until the job times out), sign
      via the spec's `codesign_identity` + entitlements, verify with
      `codesign --verify --deep --strict`.
- [ ] Notarization path. Every path below is under `dist/<version>/`, the
      directory `build.py` writes. `xcrun notarytool submit --wait` does not
      accept a bare `.app` bundle, so first zip it with `ditto -c -k
      --keepParent dist/<version>/zipseal-gui.app
      dist/<version>/zipseal-gui-app.zip` and submit that zip; staple the
      `.app` with `xcrun stapler staple dist/<version>/zipseal-gui.app`. Then
      build the DMG, sign the DMG with `codesign`, submit the DMG to
      `notarytool`, and staple the DMG with `xcrun stapler staple
      dist/<version>/zipseal-*.dmg`. Gate on `spctl --assess -t exec -v
      dist/<version>/zipseal-gui.app` for the `.app` and `spctl --assess -t
      open --context context:primary-signature -v
      dist/<version>/zipseal-*.dmg` for the DMG (without `-v`, `spctl` prints
      nothing on success).
- [ ] `.github/workflows/release.yml` triggers on `push` of tags matching
      `v*` and on `workflow_dispatch` with no inputs. Jobs: `check` (fast
      suite passes on both triggers; on a tag push, also require the tag to
      equal `v` plus the `pyproject.toml` version per Decision 9),
      `build-macos`, `publish`. `publish` runs only when
      `github.event_name == 'push'` for a tag. A `workflow_dispatch` run
      builds and smoke-tests and skips `publish`, because a branch dispatch
      has no release tag and must not create one. macOS-only at M2; Phases 3
      and 4 append `build-windows` and `build-linux` when those platforms
      land, so no job sits dead before its phase. Every action pinned by
      full SHA with a tag comment (the `check-pins` hook enforces SHA
      validity; `# tag` comments on workflow actions are repo style
      convention). Minimal top-level `permissions:`; `contents: write` only
      in `publish`; `id-token: write` + `attestations: write` for provenance.
- [ ] CI smoke: launch the built app's inner binary, wait, confirm it is
      alive, terminate. Mark advisory if the runner proves flaky; the real
      gate is the manual acceptance at the end of this phase.
- [ ] Publish job: collect artifacts, write `SHA256SUMS` (sha256 over every
      artifact), attest each artifact and the sums with
      `actions/attest-build-provenance`, then
      `gh release create vX.Y.Z --draft --title … --notes …` attaching
      everything. Release notes include the resolved Python, PyInstaller
      version, runner image, and Tk version per artifact, the measured Linux
      glibc floor, the `SHA256SUMS` verification line, and the
      `gh attestation verify` line.
- [ ] `dev-docs/releasing.md` (new durable doc): the tag-to-release runbook,
      the secrets list (names only), rollback (delete draft → delete tag → fix
      → re-tag), and the acceptance checklist from M1–M3. Add it to
      `REQUIRED_FILES` in `hooks/scripts/check_doc_freshness.py` and to the
      durable-doc list in `dev-docs/README.md` so the freshness hook covers it.
- [ ] Rehearse first: run the workflow with `workflow_dispatch` (the
      `release.yml` bullet above). That builds the artifact and skips
      `publish`. Pushing a tag is what creates the draft release, so a
      rehearsal tag would not do. Then the first real run at the next version
      bump; v0.1.0 stays source-only.
- [ ] Manual acceptance (from M2 on, on a machine without Python): download
      the drafted release asset fresh (the browser sets the quarantine flag),
      open the DMG, drag to Applications, launch, create an archive with a
      generated password, open it in Finder and 7-Zip. Record the date and
      macOS version here.

## Phase 3 — Windows app

- [ ] Build the onedir zip on `windows-latest` with the uv-managed Python;
      embed the exe icon and the file version resource.
- [ ] CI smoke: start `zipseal-gui.exe`, wait, confirm it is alive, stop it.
      A failure fails the job.
- [ ] Manual acceptance (drafted release, on a machine without Python):
      download the zip, unzip, run `zipseal-gui.exe`, create an archive with a
      generated password, and open it in 7-Zip (Explorer's built-in zip
      support is unreliable for AES; see `user-docs/opening-archives.md`).
      Record the date and Windows version here.
- [ ] Resolve signing (Decision 3) on both tracks:
  - SignPath Foundation application — only after the first tagged release has
    shipped the (unsigned) zip: SignPath requires the project to be already
    "released in the form that should be signed", and the application needs
    the Releases-page download URL. Add the required "Code signing policy"
    section to `README.md` with their exact wording (re-verify the sentence
    against signpath.io at application time; the 2026-11-02 snapshot is
    "Free code signing provided by SignPath.io, certificate by SignPath
    Foundation"), list committer/approver roles, then apply with the
    repository and download URLs. If approved, integrate their GitHub Action,
    pin it by SHA, and keep per-release approvals in mind.
  - Store MSIX spike: free individual Partner Center account, package the
    onedir as a full-trust MSIX, submit once, confirm Microsoft re-signing
    removes SmartScreen warnings. Decision after the spike; do not commit to
    the Store before it passes certification once.
  - Until signed: document "More info → Run anyway", note Smart App Control on
    Windows 11 may block unsigned apps, and submit any AV false positive to
    Microsoft's portal.
- [ ] Optional, deferred until asked: Inno Setup installer (the portable zip is
      the artifact this plan promises) and a winget manifest PR.

## Phase 4 — Linux app

- [ ] Build inside a pinned `ubuntu:22.04` container. That image has glibc
      2.35; the PyInstaller bootloader itself is glibc 2.17+. Neither number
      is the shipped floor. After the build, read the glibc requirement from
      the bundled Python, Tcl/Tk and extension modules (Risk 8) and record
      that measured floor in the release notes. Produce the onedir tree, then
      an AppImage via a pinned `appimagetool`, and also the `.tar.gz`.
      `appimagetool` is
      itself a Type 2 AppImage and will not run inside an unprivileged
      container without `/dev/fuse`, so extract it first (`./appimagetool-x86_64.AppImage --appimage-extract`) and invoke
      `ARCH=x86_64 ./squashfs-root/AppRun dist/<version>/AppDir ...` with
      `APPIMAGE_EXTRACT_AND_RUN=1`. The container needs `file`, `binutils`
      (PyInstaller shells out to `objdump`/`objcopy`), `libc-bin` (for
      `ldd`), `desktop-file-utils` (`desktop-file-validate`), plus `xvfb` and
      `xdotool` for the smoke test below.
- [ ] AppDir contents: `zipseal-gui.desktop` (`Terminal=false`,
      `Categories=Utility;Security;`), `AppRun`, generated icon.
- [ ] CI smoke under `xvfb-run`: launch, wait, assert the process is alive, and
      if practical assert a window named `zipseal` exists
      (`xdotool search --name`), then terminate. A failure fails the job.
- [ ] Manual acceptance (drafted release, on a machine without Python):
      download the AppImage and the `.tar.gz`; extract the `.tar.gz` and run
      the binary; run the AppImage (use `--appimage-extract-and-run` if FUSE
      is unavailable); create an archive with a generated password, and open
      it in 7-Zip or `bsdtar`. Record the date and distro here.
- [ ] Docs: `chmod +x`, the FUSE fallback
      (`./zipseal-gui.AppImage --appimage-extract-and-run`), and that the
      `.tar.gz` runs from any folder.

## Phase 5 — Docs

- [ ] `README.md` Install: a downloads table (macOS / Windows / Linux), the
      measured Linux glibc floor from the release notes, and `uv tool install`
      for the CLI.
- [ ] `user-docs/gui.md` "Start it" → "Get the app": per-OS first-run notes
      (macOS: nothing to do; Windows: SmartScreen; Linux: chmod +x).
- [ ] New `user-docs/troubleshooting-app.md` (or a section): SmartScreen, Smart
      App Control, AV false positives, AppImage FUSE, "where does it write?",
      and how to tell which version is installed (the download filename and
      the release page — the frozen window shows no version).
- [ ] `AGENTS.md`: build command, `packaging/` in the layout, release workflow.
- [ ] `SPEC.md`: the packaging line (around line 106) becomes the artifact
      table above; note the GUI ships frozen while the CLI stays source.
- [ ] `CHANGELOG.md` (user-visible) and `CHANGELOG.dev.md` (workflow internals);
      doc-gardening pass; bump `Last reviewed` dates after re-reading.

## Phase 6 — CLI on PyPI (optional, decide after M3)

- [ ] `uv build` and publish via PyPI Trusted Publishing (`id-token: write`,
      `pypi` environment), gated behind a `workflow_dispatch` job or a
      protected `pypi` environment requiring approval — never implicitly on
      every tag, because PyPI versions are immutable and a re-cut tag cannot
      re-upload. Name `zipseal` is free (checked 2026-11-02).
- [ ] README: `uvx zipseal` as the one-line CLI install.
- [ ] Only worth doing if installing the CLI without a git URL is wanted; it
      changes nothing for GUI users.

## Test list

Each behavior gets a pytest test per repo convention. Packaging tests:

- [ ] `read_version()` returns `pyproject.toml`'s version; a version
      substitution render (Info.plist fields, Windows version resource string)
      contains it.
- [ ] The artifact globs (`*.dmg`, `*.msi`, `*.exe`, `*.AppImage`, `*.tar.gz`)
      are present in `.forbidden-paths` and the output roots (`dist/`, `build/`)
      are ignored by `.gitignore`; a synthetic untracked artifact under `dist/`
      fails the forbidden-paths hook when tracked.
- [ ] `packaging/linux/zipseal-gui.desktop` has `Name`, `Exec`, `Icon`,
      `Terminal=false`, sorted `Categories`; `AppRun` is tracked executable.
- [ ] `packaging/macos/entitlements.plist` parses with `plistlib` and contains
      `com.apple.security.cs.allow-unsigned-executable-memory` and
      `com.apple.security.cs.disable-library-validation` (Decision 4 — removal
      requires a Decision 4 note).
- [ ] `collect_data_files()` includes `src/zipseal/icon.svg` (the freeze-time
      icon dependency), matching `gui.ICON`'s source path.
- [ ] If the PNG fallback lands: `tests/test_window_icon.py` gains a case for
      "SVG raises TclError, PNG present, icon set from PNG", and "neither
      present, returns False and the launch is unaffected".

CI smoke gates (not pytest): the per-platform launch checks run
against the artifact the workflow uploads. Windows and Linux fail the job
when the process does not stay alive. The macOS launch check may be advisory
when the runner is flaky; that job still gates on `codesign`/`spctl`/`stapler`.
Manual acceptance of the drafted artifact, on a machine without Python, is
recorded in this plan with a date for each platform and is the blocking gate
for publish.

## Secrets to set up (names only)

`APPLE_CERT_P12` (base64 Developer ID Application .p12), `APPLE_CERT_PASSWORD`,
`APPLE_TEAM_ID`, `APPLE_API_KEY_ID`, `APPLE_API_ISSUER_ID`,
`APPLE_API_PRIVATE_KEY` (base64 .p8), `KEYCHAIN_PASSWORD` (ephemeral chain).
`SIGNPATH_*` only if Phase 3 signing is approved. Linux needs no secrets.
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
5. **Intel macOS**: no build (arm64 only, Decision 8); GitHub ends x86_64
   macOS runners entirely in Fall 2027. Intel Macs use the source install.
6. **Tk version per platform** decides the window icon (cosmetic; the file icon
   is separate). Verified per artifact and recorded in the release notes.
7. **Size**: expect roughly 15–40 MB per artifact. If that matters, revisit
   `excludes` — not a gate.
8. **Run-time floors** (macOS minimum, glibc, Windows version) come from the
   bundled binaries — Python, Tcl/Tk and the extension modules — not from
   Python's docs; measure and document the real ones.

## Milestones

- **M1**: local macOS `zipseal-gui.app` runs from `dist/<version>/`, does a
  real archive;
  Phase 0 tests green. No CI yet.
- **M2**: tagged workflow produces a signed, notarized, stapled DMG as a draft
  release; manual acceptance recorded; maintainer publishes.
- **M3**: Windows zip and Linux AppImage + tar.gz join the same workflow,
  smoke-tested in CI, accepted on a machine without Python, `SHA256SUMS` +
  attestations attached; Windows signing resolved one way or the other.
- **M4**: README, `user-docs/`, `AGENTS.md` and `SPEC.md` updated;
  `dev-docs/releasing.md` finalized (created and freshness-hooked in Phase 2);
  PyPI decision recorded.

## Review changes

- 2026-11-02: An antigravity/gemini-3.8-flash-high review (4 blockers, 6
  majors, 6 minors) led to these changes: pre-populated macOS entitlements;
  `ditto` zip before `notarytool`; `security set-key-partition-list` in CI;
  appimagetool extracted before running in a container (no `/dev/fuse`);
  `spctl -t open --context context:primary-signature -v` for DMGs; `*.tar.gz`
  added to the artifact globs; `dev-docs/releasing.md` registered with the
  doc-freshness hook; phases re-aligned to milestones; the
  `packaging/run_gui.py` entry point; uniform `zipseal-gui-*` artifact naming;
  generated icons written to `build/icons/`.

- 2026-11-03: A self-review found Decision 5 missing `*.tar.gz` and Phase 0
  calling the entitlements file an empty dict against Decision 4; both fixed.

- 2026-11-03: A second self-review fixed two markdown rendering defects (a
  glued checklist item and a broken code span), moved the CI smoke and the
  draft-release acceptance out of M1 into Phase 2 (M1 has no CI), corrected
  the Linux container package list (`binutils`, `libc-bin`, `xvfb`,
  `xdotool`), made `release.yml` macos-only at M2 with later phases appending
  their jobs, aligned the M4 milestone with `releasing.md`, reworded Phase 3
  to pursue SignPath and the Store in parallel (SignPath applied only after
  the first unsigned release ships), softened the entitlements claim to an
  empirically verified default, gated PyPI publishing behind an explicit
  dispatch or environment approval, added how-to-identify-the-version to the
  troubleshooting docs, and deferred Linux/Windows arm64 to `TODO.md` via the
  non-goals.

- 2026-11-04: A CodeRabbit review, then an agy/gemini-3.8-flash-high review
  of those fixes. The release workflow requires the tag to equal `v` plus
  the `pyproject.toml` version (no prefix stripping) and skips that check
  on `workflow_dispatch`. `workflow_dispatch` takes no inputs and cannot
  publish; only a tag push runs `publish`. TODO.md names the Linux
  `.tar.gz` and the `uv tool install` CLI contract.

- 2026-11-04: A second CodeRabbit review. The release contract now matches
  the gates: CI smoke is a liveness check and may be advisory on macOS only,
  and each platform's drafted artifact is accepted on a machine without
  Python. Decision 1's glibc 2.17 is the bootloader floor; the shipped floor
  is measured from the bundle. Signing and notarization paths use
  `dist/<version>/`. The pre-populated Hardened Runtime entitlements stay;
  an empty plist was not adopted.

- 2026-11-04: An OpenCode DeepSeek V4.1 Flash review of those gates. Windows
  acceptance opens the archive in 7-Zip, because Explorer's AES support is
  unreliable. macOS acceptance runs on a machine without Python. The goal
  states that only Windows and Linux CI smoke fails the job. Risk 8 measures
  Python, Tcl/Tk and extension modules. The release-notes glibc floor is
  Linux-only. Linux acceptance names the AppImage FUSE fallback and 7-Zip
  or `bsdtar`.
