# Plan: GUI executables for macOS, Windows and Linux

Date: 2026-11-02
Status: in-progress
Linked: TODO.md "Ship `zipseal-gui` as downloadable apps…"; supersedes the
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
smoke launches that same artifact; Windows and Linux fail the job, the macOS
check may be advisory, and `codesign`/`spctl`/`stapler` still fail it. Before
publishing, the drafted artifact for every platform the release contains
(macOS at M2; Windows and Linux from M3) is accepted on a machine with no
user-installed Python on `PATH` (no uv-managed, pyenv or Homebrew
interpreter): launch it, create an archive with a generated password, open
it. The Apple-provided `/usr/bin/python3` may be present; it ships with the
OS and is not a user install. On macOS a clean Standard second account is
equivalent to a clean VM. The smoke-tested artifact is what ships, never a
second local build.

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
   (`--codesign-identity`, hardened runtime) and produces `onedir` and
   `onefile`; `onedir` keeps AV false positives rare and startup fast.
   **Briefcase is rejected**: its Windows
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
   `_tkinter`/`libtcl`/`libtk` landed in 2025. The build script pins an exact
   python-build-standalone release (a date-stamped asset, so a rebuild gets the
   same interpreter); the resolved Python and Tk versions go in the release
   notes. Start on the highest minor CI tests — 3.13 today; `.python-version`
   (3.12) only drives local `uv` runs — and revisit 3.14 for Tk 9 on Windows if
   the window icon is judged to matter (Decision 7).
3. **Windows signing: do not buy Azure Artifact Signing.** Microsoft's current
   docs (2026-08-29) say it costs $9.99/month *and* gives no instant
   SmartScreen trust — reputation builds over time; individual developers are
   limited to the USA/Canada. EV certificates stopped bypassing SmartScreen in
   2024, so the premium is pointless. Both free routes are pursued:
   - **SignPath Foundation**: free OV-level signing for qualifying OSS
     projects (SignPath's certificate and HSM; publisher shows as "SignPath
     Foundation"). It Authenticode-signs `zipseal-gui.exe` and every bundled
     DLL inside the zip `build-windows` uploads — signing the archive itself
     does nothing for SmartScreen, which reads the signature of the
     executable the user runs. Apply with the repository and download URLs, add the required
     "Code signing policy" section to `README.md` with their exact wording and
     role list, then integrate their GitHub Action (pinned by SHA) with
     per-release approvals. Verify the shipped artifact, not the build tree:
     extract `zipseal-gui.exe` from the final zip and run
     `signtool verify /pa /v` in CI and again at manual acceptance.
   - **Microsoft Store (MSIX)**: individual registration is free since
     September 2025, and Store MSIX packages are re-signed by Microsoft — the
     only recorded way to zero SmartScreen warnings. Run a time-boxed spike:
     package the onedir as a full-trust MSIX and submit once; decide only
     after it passes certification and re-signing is confirmed to remove the
     warnings.
   - **In parallel until one lands**: the zip ships unsigned with documented
     "More info → Run anyway" steps and a note that Windows 11 Smart App
     Control may block unsigned apps outright. No calendar cost, only
     documentation debt. Each route signs a different thing: SignPath signs
     `zipseal-gui.exe` inside the zip, while the Store re-signs only the MSIX
     it distributes, so the zip's executable stays unsigned if the Store is
     the route that lands. "Windows signing resolved" always names the
     artifact that is actually signed.
4. **macOS: Developer ID + notarization** (the Apple Developer account is
   already available). Sign the `.app` with hardened runtime and a secure
   timestamp, notarize with `notarytool` using an App Store Connect API key,
   staple the `.app` and the DMG, and gate CI on `codesign --verify --deep
   --strict`, `spctl --assess -t exec -v` and `stapler validate`. Start with
   an empty `packaging/macos/entitlements.plist`, then add
   `com.apple.security.cs.allow-unsigned-executable-memory` or
   `com.apple.security.cs.disable-library-validation` only after a
   reproducible W^X or loader failure on the exact signed bundle, recording
   the failing log and the entitlement that fixed it here. Both exceptions
   weaken hardened runtime (unsigned executable memory, library validation
   off), so neither is carried "just in case", and release acceptance rejects
   any entitlement the bundle does not demonstrably need. Risk 3 expects this
   iteration.
5. **Nothing build-output is ever committed.** `dist/` and `build/` are already
   in `.gitignore`; extend both `.gitignore` and `.forbidden-paths` with the
   artifact globs (`*.dmg`, `*.msi`, `*.exe`, `*.AppImage`, `*.tar.gz`) so even a
   force-added artifact cannot be committed.
6. **Release mechanics**: tag `vX.Y.Z` → `release.yml` builds on versioned
   runner images (`macos-15`, `windows-2025`, `ubuntu-24.04`; never `-latest`,
   so a tag cannot change under the project without a commit; a bump of any
   of those labels, or of the Linux image digest, is its own commit, recorded
   in `dev-docs/releasing.md` with the previous value) → the tag push re-runs
   `ci.yml`'s gates inside `release.yml`, because `ci.yml` does not run on
   tags → smoke tests →
   writes `SHA256SUMS` → attests each artifact (`attest-build-provenance`
   v4.x, free on public repos) → creates a **draft** release the maintainer
   publishes after manual acceptance. A `workflow_dispatch` rehearsal skips
   the signing job and never sees the signing secrets; `publish` is tag-only,
   grouped per tag, and asserts the tag's commit (Phase 2).
7. **Icons are generated at build time from `src/zipseal/icon.svg`**
   (nothing raster enters the repo; `*.png` is blocked by design). One pinned
   toolchain, not "or platform tools": `resvg` (checksummed static binary)
   renders the PNGs, Pillow (in the `build` group, excluded from the bundle)
   packs the multi-size `.ico`, and macOS `iconutil` turns an `.iconset` into
   the `.icns` — the macOS build runs on a macOS runner, so it is present.
   Linux needs one PNG for the `.desktop` icon. The app's `gui_view.set_icon`
   already prefers Tk 9's SVG reader; where a bundle carries Tk 8.6, the
   generated PNG is the fallback so the window and taskbar still get the
   zipseal icon.
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

- [x] Audit the GUI's frozen-run assumptions. Today the only file reference is
      `gui.ICON = Path(__file__).with_name("icon.svg")` (`gui.py:168`), loaded
      by `gui_view.set_icon` with Tk's SVG reader. `build.py`'s
      `resolved_data_files()` is what the `.spec` uses for `datas`. It
      absolutizes `collect_data_files()`, which returns both
      `("src/zipseal/icon.svg", "zipseal")` and
      `("build/icons/icon.png", "zipseal")` rather than a handwritten PNG
      tuple: a frozen module's
      `__file__` is `sys._MEIPASS/zipseal/gui.py`, so the icon has to land in
      `_MEIPASS/zipseal/`, and a `"."` destination would put it at the bundle
      root where `set_icon` silently returns False when the SVG and its PNG
      sibling are both missing. A smoke check asserts the resolved path
      exists in the frozen tree. No cwd or `__file__` use
      elsewhere.
- [x] Add a `build` dependency group to `pyproject.toml`
      (`pyinstaller==6.22.3` first entry; locks into `uv.lock`, Dependabot
      bumps it). Builds run as `uv run --group build`.
- [x] Extend `.gitignore` and `.forbidden-paths` with the artifact globs
      (`*.dmg`, `*.msi`, `*.exe`, `*.AppImage`, `*.tar.gz`) so even a
      force-added artifact cannot be committed; confirm `dist/` and `build/`
      are in both files' spirit (already ignored; add to `.forbidden-paths`).
- [x] Create `packaging/`:
  - `run_gui.py` — the PyInstaller entry point: `import sys; from zipseal.gui import main; sys.exit(main())`.
    Neither `gui.py` nor `gui_view.py` has an `if __name__ == "__main__"` block, so this thin script
    is what the `.spec` targets.
  - `build.py` — one entry point:
    `uv run --group build python packaging/build.py --target {macos,windows,linux}`
    with `--skip-sign` (local runs and `build-macos`; signing lives in
    `sign-macos`) and `--version` defaulting to `pyproject.toml`. Outputs
    under `dist/<version>/`. The interpreter is
    pinned by exact version from one shared constant: the job runs `uv python
    install <pin>` then `uv run --python <pin> --group build …`, and
    `build.py` fails unless `platform.python_version()` matches, so
    `.python-version` (3.12) cannot leak into a release. Before freezing it
    runs a per-target preflight under the target's display setup (none on
    macOS and Windows, `xvfb-run` in the Linux container): import
    `tkinter`, create and destroy a `tk.Tk()` root, and assert that Tcl/Tk
    resolve to support files inside the extracted Python distribution, so a
    build that silently picks up the host's Tcl/Tk fails there instead of on
    a user's machine. It runs `icons.py` before freezing, on every target,
    and fails with an explicit message if `build/icons/icon.png` is still
    missing; the `.ico`, `.icns` and desktop PNG come from that same tree.
  - `zipseal-gui.spec` — onedir, windowed, entry point `run_gui.py`,
    `name="zipseal-gui"`, macOS BUNDLE `zipseal-gui.app`, bundle id, version
    substitution, `datas` (the SVG and the generated PNG), and `excludes`
    (`pytest`, `hypothesis`, `basedpyright`, `yaml`) — build-only tools such
    as Pillow and `resvg` never enter the bundle, because the entry point is
    `run_gui.py`.
  - `macos/entitlements.plist` — empty at first; add one entitlement at a
      time only for a reproducible failure, with the log recorded per
      Decision 4.
  - `windows/version_info.txt`; `linux/zipseal-gui.desktop` and
      `linux/AppRun` for the AppImage.
  - `icons.py` — SVG → PNG (`resvg`), `.ico` (Pillow, `build` group) and
      `.icns` (`iconutil`, macOS runner) at build time; pinned tools.
      `resvg` is fetched into `build/tools/` (gitignored) with a pinned
      checksum, so the binary is never a candidate for staging.
      Generated rasters are written to `build/icons/` (never `src/`, since
      `*.png` is blocked by `.forbidden-paths`), and the window-icon PNG is
      bundled with `datas=[("build/icons/icon.png", "zipseal")]`, beside
      `ICON` under `_MEIPASS/zipseal/`, which the PNG-fallback task reads.
- [x] `gui_view.set_icon` loads `ICON.with_name("icon.png")` when SVG loading
      fails. That is the PNG bundled at `_MEIPASS/zipseal/` next to `ICON`.
      Tk 9 still prefers the SVG. If the PNG is missing or unreadable too,
      return False and leave Tk's default icon; a missing icon never fails
      launch. Acceptance is the two `tests/test_window_icon.py` cases in the
      test list: the PNG is shown when SVG raises `TclError`, and the default
      icon remains when neither image loads.
- [x] Bring `packaging/` under the existing quality gates, or its first
      commit fails `pre-commit run --all-files`: add it to
      `[tool.basedpyright].include` (`pyproject.toml`, today `["src",
      "tests"]`) and the basedpyright hook's `files:` regex, and add
      `"packaging/**" = ["S603", "S607"]` to `ruff.toml` (`build.py` shells
      out to `hdiutil`, `codesign`, `xcrun`, `objcopy`, `appimagetool`).
- [x] `tests/test_packaging.py` covering the test list below; load
      `packaging/build.py` with `importlib.util.spec_from_file_location`, as
      `tests/test_check_pins.py` loads its hook, and never add `packaging` to
      pytest's `pythonpath` — it would shadow the PyPI `packaging`
      distribution for anything in the pytest process that imports it.
- [x] `AGENTS.md` command for a local build; `dev-docs/README.md` unchanged in
      this phase (Phase 2 registers `releasing.md` there).

## Phase 1 — macOS app (milestone M1)

- [x] Build a local unsigned `zipseal-gui.app`; open it from `dist/<version>/`
      and run a real archive end to end (same inputs as the GUI plan smoke
      test). Done 2026-11-15 from `dist/0.1.0/zipseal-gui.app`.
- [x] `Info.plist`: `CFBundleShortVersionString`/`CFBundleVersion` from
      `pyproject.toml`, a reverse-DNS `CFBundleIdentifier` derived from the
      GitHub owner (record the exact id when implementing),
      `CFBundleName`/`CFBundleDisplayName` `zipseal`, `CFBundleIconFile`,
      `NSHighResolutionCapable`, `LSApplicationCategoryType`
      (`public.app-category.utilities`), `NSHumanReadableCopyright`, and
      `LSMinimumSystemVersion` from what the bundled Python supports — verify
      on the oldest macOS you can; do not guess the floor.
      The keys are rendered, the id is `io.github.kgforais1.zipseal-gui`, and
      `LSMinimumSystemVersion` is `11.0`, the pinned 3.13.17 `libpython`
      `LC_BUILD_VERSION` minos measured 2026-11-15. No macOS 11 machine is
      available, so that launch will not be done. The declared floor stays
      the measured Mach-O minimum.
- [x] Make the DMG: `hdiutil create -format UDZO`, `zipseal-gui.app` plus an
      Applications symlink (drag-install). The image is written into
      `dist/<version>.partial` and that tree replaces `dist/<version>/` only
      after `hdiutil` succeeds.
- [x] Manual acceptance (local build — M1 has no CI): open the DMG, drag the
      app to Applications, then set a synthetic `com.apple.quarantine` xattr
      on the installed copy so the Gatekeeper path is exercised. The unsigned
      build is expected to be refused; confirm the block, then launch anyway
      (macOS 15+ removed the Control-click override: System Settings →
      Privacy & Security → "Open Anyway"; older macOS: Control-click the app
      → Open) and finish the check: create an archive with a generated
      password and open it in Finder and 7-Zip. Record the date, macOS
      version and the override path used. Done 2026-11-15 on macOS 26
      (darwin 25.6.0): the quarantined Applications copy was refused, launched
      with Privacy & Security → Open Anyway, and that copy created an archive
      which was opened. The download-from-the-draft-release
      variant runs from M2 on (the last bullet of Phase 2).

## Phase 2 — macOS signing, notarization & release pipeline (milestone M2)

- [x] Create the `release` environment and two `v*` tag rulesets before any
      signing secret is stored. Deployment branches and tags are `v*` only,
      with both a `branch` and a `tag` policy, recorded in `dev-docs/releasing.md`
      together with the exact calls. The maintainer changed the environment in
      the UI (required reviewers `kgforais1` and `kgrizz-git`,
      `prevent_self_review` off, `can_admins_bypass` on) and on 2026-11-17
      explicitly accepted the one-account control; both accounts are theirs,
      so the approval is the maintainer's own. The two rulesets are as
      specified: creation limited to the tag-pushing account, immutability
      with an empty bypass list, so a tag move is blocked regardless of
      account.
      Note:
      Created 2026-11-15/2026-11-16 under `kgforais1`'s fine-grained PAT via
      `.context/gh-pat.sh`; see `dev-docs/releasing.md` for the exact calls and
      for the live state. The six Apple secrets were stored 2026-11-18 (see
      `dev-docs/releasing.md`). The two rulesets are
      as specified: creation limited to the tag-pushing account, immutability
      with an empty bypass list.
      The control is the two-account split: tag pushes are created by
      `kgrizz-git`, the `release` environment's reviewer is the owner.
      The creation ruleset targets `v*` with Restrict creations, and its only
      bypass is the tag-pushing account. The immutability ruleset targets
      `v*` with Restrict updates and Restrict deletions, and its bypass list
      is empty: the tag-pushing account is not on it and cannot change or
      remove a tag. Deleting a tag for rollback is a temporary entry on that
      bypass list, added by the account that can edit rulesets (not the
      tag-pushing account). That account adds itself, deletes the tag, and
      removes the entry in the same session, before the replacement tag is
      pushed. An empty list blocks every actor, including the owner, so
      there is no other route, and leaving the entry in place drops
      immutability for every `v*` tag. This repository is not an
      organization, so the add and the remove are written by hand into the
      release's rollback note. The tag-pushing account, the only creation
      bypass, then pushes the replacement tag. `dev-docs/releasing.md` records
      the exact settings and both account names (created 2026-11-15:
      `kgrizz-git` has only push, not admin, so the calls ran under a
      `kgforais1` fine-grained PAT). Note: the owner later changed the
      environment's required reviewers and `prevent_self_review` in the UI
      (both accounts are theirs); that state is recorded in
      `dev-docs/releasing.md` rather than assumed to be the intended split.
- [x] CI signing path (tag pushes only, inside `sign-macos`). The keychain
      password is generated per run (`openssl rand -base64 32`, masked), not
      a stored secret (amended 2026-11-18). `security
      create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"`, `security
      unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"`, `security
      list-keychains -d user -s "$KEYCHAIN_PATH" login.keychain` (without the
      search-list entry `codesign` fails with "no identity found"), then
      import the `.p12` (`security import ... -k "$KEYCHAIN_PATH" -P
      "$APPLE_CERT_PASSWORD" -T /usr/bin/codesign`) and only after that run
      `security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k
      "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"` against the imported key
      (without it `codesign` pops a GUI prompt in headless CI and hangs until
      the job times out). Then sign inside out. `codesign` on the `.app` does
      not sign nested code, and `--deep` is not used to sign (Apple TN2206;
      the verify step below is where `--deep` belongs). First, deepest path
      first, sign every nested Mach-O that `codesign` can sign. Enumerate
      with `find dist/<version>/zipseal-gui.app -type f` so framework
      symlinks are not walked; the enclosing `.framework` seals them. Keep a
      file only when `file`'s description contains `Mach-O` and is not an
      object file, and skip `.o` and `.a`. `file` reports `python.o` as
      `Mach-O … object`, and `codesign` then fails with "code object is not
      supported at all". The kept set still includes PyInstaller's `.dylib`
      and `.so` files and extension-less binaries such as
      `Python.framework`'s `Python`. Log each path and its `file` line. Each
      gets the Developer ID identity, hardened runtime, and a secure
      timestamp, and not the entitlements plist: `codesign --force --options
      runtime --timestamp --sign "$IDENTITY" <nested>`. Sign any enclosing
      `.framework` the same way after its contents. Only after those
      signatures exist, sign the outer bundle: `codesign --force --options
      runtime --timestamp --entitlements packaging/macos/entitlements.plist
      --sign "$IDENTITY" dist/<version>/zipseal-gui.app`. Before notarizing,
      `codesign -dv --verbose=4` on that bundle must show `Authority=Developer
      ID Application:` together with `APPLE_TEAM_ID`, and
      `flags=0x10000(runtime)`. Ad-hoc (`-`) or an Apple Development identity
      fails the job here, not at `notarytool`. The spec leaves
      `codesign_identity` unset and `build-macos` always passes `--skip-sign`,
      so freezing and signing stay in separate jobs. Verify with `codesign
      --verify --deep --strict`, and run `security delete-keychain
      "$KEYCHAIN_PATH"` from an `if: always()` step.
- [x] Notarization path. Every path is under `dist/<version>/`, the directory
      `build.py` writes. `notarytool submit --wait` rejects a bare `.app`, so
      zip it first (`ditto -c -k --keepParent dist/<version>/zipseal-gui.app
      dist/<version>/zipseal-gui-app.zip`), submit, then staple the `.app`.
      Then build the DMG with Phase 1's `hdiutil create -format UDZO` recipe
      around the stapled `.app` (Phase 1's copy wraps an unsigned app and
      stays local) and sign the image: `codesign --force --timestamp --sign
      "$IDENTITY" dist/<version>/zipseal-gui-<version>-macos-arm64.dmg`.
      Hardened runtime does not apply to a disk image. Notarize and staple
      the DMG. Gate on `xcrun stapler validate` for both the `.app` and the DMG, `spctl --assess -t
      exec -v dist/<version>/zipseal-gui.app`, and `spctl --assess -t open
      --context context:primary-signature -v dist/<version>/zipseal-*.dmg`
      (without `-v`, `spctl` prints nothing on success).
- [x] `.github/workflows/release.yml` triggers on `push` of tags matching
      `v*` and on `workflow_dispatch` with no inputs. Jobs: `check-hooks`,
      `check-test`, `check-audit`, `build-macos`, `sign-macos`, `publish`.
      `ci.yml` runs on pushes to `main` and on pull requests only, so a tag
      runs none of it. The three check jobs re-run those gates on both
      triggers. `check-hooks` is `ci.yml`'s `checks` job with the same steps
      except the sync, plus the tag check below; the checkout step with `fetch-depth: 0` and
      `persist-credentials: false`, `setup-uv` reading the one uv pin in
      `.github/uv.toml` (`version-file`),
      `uv sync --locked --no-build --no-install-project` (the hardened sync —
      hardened so SonarCloud's S8541 `--no-build` rule passes; the `check-pins`
      and `basedpyright` hooks still run their own `uv run`, basedpyright with
      `--group build`),
      then `uvx --no-build
      pre-commit==4.7.0 run --all-files --show-diff-on-failure`. `check-audit` is `ci.yml`'s
      `audit` job unchanged (`pip-audit==2.10.1`). `check-test` is `ci.yml`'s
      `test` job — same runners, matrix and gates as `ci.yml`, with the
      `uv` commands the documented divergence from `ci.yml` (hardened for Sonar
      Cloud S8541/S8544: `--no-build`, `--no-install-project`, `PYTHONPATH=src`):
      `timeout-minutes: 30`, matrix
      `os: [ubuntu-latest, macos-latest]` × `python: ["3.11", "3.13"]`,
      `fail-fast: false`, checkout with `persist-credentials: false`,
      `setup-uv` reading `.github/uv.toml` with
      `python-version: ${{ matrix.python }}`, Linux
      `sudo apt-get update && sudo apt-get install -y 7zip libarchive-tools`,
      macOS `brew install sevenzip`, then `uv sync --locked --no-build
      --no-install-project`, and
      `PYTHONPATH=src uv run --locked --no-build --no-sync pytest -q` (the
      fast suite — `addopts` drops `slow` and `gui`; zipseal is imported from
      `src/`, not installed).
      Those are the test runners `ci.yml` uses, separate from the versioned
      build images in Decision 6. On a tag push `check-hooks` also requires
      the tag to equal `v` plus the `pyproject.toml` version (Decision 9).
      The check jobs have no `needs`. `build-macos` has
      `needs: [check-hooks, check-test, check-audit]`, and `sign-macos` has
      `needs: build-macos`, so a red gate never reaches the Apple secrets or
      `notarytool`. `build-windows` and `build-linux` take that same `needs`
      when they land. At M2, `publish` has `needs: [check-hooks, check-test,
      check-audit, sign-macos]`. `needs: check-test` waits for every matrix
      cell; one red cell fails that job and blocks the draft. Phase 3 adds
      whichever job uploads the zip that ships
      (`sign-windows` once it repacks, otherwise `build-windows`); Phase 4
      adds `build-linux`. A failed need blocks the draft. `publish`'s own
      `if` still skips it on a dispatch, where `sign-macos` is skipped too.
      `publish` runs only when
      `github.event_name == 'push'` for a tag, checks out with
      `fetch-depth: 0` and credentials kept (this repo uses
      `persist-credentials: false` elsewhere; without them `ls-remote` is
      anonymous), and starts by asking the remote where the tag points:
      `git ls-remote --tags origin "refs/tags/$GITHUB_REF_NAME"` returns the
      tag ref, plus a peeled `^{}` entry for an annotated tag; compare the
      peeled SHA with `GITHUB_SHA` when present and the tag ref's own SHA for
      a lightweight tag (the local ref only shows what was fetched). It then
      runs `gh release create --verify-tag`, so a moved or deleted tag fails
      instead of shipping under a label that points elsewhere. The two `v*`
      rulesets are the setup task's: the tag-pushing account can create a
      tag and cannot update or delete one.
      `concurrency: group: release-${{ github.ref_name }}` with
      `cancel-in-progress: false` keeps two runs from publishing one version.
      Signing needs its own job: `environment` is job-level only, and a
      `release` environment restricted to `v*` tags fails any job that
      requests it from a branch ref — which is what a dispatch gives you. So
      `build-macos` runs on both triggers with no environment and no secrets
      (build, smoke test, upload), and `sign-macos` is guarded by
      `if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')`,
      declares `environment: release` (restricted to `v*`, required reviewer,
      self-review prevented), downloads the archived `.app`, extracts it
      (`ditto -x -k`) so permissions and symlinks survive, and signs,
      notarizes, staples and builds the DMG around it, then uploads only the
      signed DMG under its own artifact name (`zipseal-gui-macos-dmg`).
      `build-macos`'s `.app` archive uses a different name, and `publish`
      downloads by `name:`, so the intermediate never reaches `SHA256SUMS`,
      the attestation or the release. `build-macos` archives
      the bundle before upload (`ditto -c -k --keepParent`), because the
      artifact store does not preserve the executable bit. Only a signature is
      added, so the smoke-tested artifact is still what ships. The event guard
      is load-bearing: a dispatch can target a `v*` tag, so the ref test alone
      would request the environment. That split is a second GitHub account as
      the required `release` reviewer, with Prevent self-review on and Allow
      administrators to bypass off. The account allowed to push `v*` tags is
      not that reviewer, so it cannot approve its own secret access or skip
      the rule. Without the second account, or with administrator bypass left
      on, one account can both push the tag and reach the secrets, and the
      approval guarantee does not hold. `publish`
      takes no environment, and a dispatch skips it.
      macOS-only at M2; Phases 3 and 4 append `build-windows`/`sign-windows`
      and `build-linux` when those platforms land, so no job sits dead before
      its phase. Every action pinned by full SHA with a tag comment (repo
      style; `check-pins` enforces validity). Minimal top-level
      `permissions:`. `contents: write`, `id-token: write` and
      `attestations: write` are on `publish` only, so provenance is minted
      after the `needs` jobs have produced the bytes that ship.
- [x] CI smoke: launch the built app's inner binary, wait, confirm it is
      alive, terminate. Mark advisory if the runner proves flaky; the real
      gate is the manual acceptance at the end of this phase.
- [x] Publish job: collect the artifacts its `needs` uploaded — the signed
      DMG, and later the repacked Windows zip rather than the unsigned one.
      Write `SHA256SUMS`, attest each artifact
      and the sums with `actions/attest-build-provenance`, then
      `gh release create vX.Y.Z --draft --verify-tag --title … --notes …`
      attaching everything (`--verify-tag` refuses to create the tag itself,
      which would otherwise happen silently from the default branch). Release
      notes include the resolved Python, PyInstaller, runner image and Tk
      version per artifact, the measured Linux glibc floor, and the
      `SHA256SUMS` / `gh attestation verify` lines.
- [x] `dev-docs/releasing.md` (new durable doc): the tag-to-release runbook,
      the secrets list (names only), rollback (delete draft → delete tag → fix
      → re-tag; the ruleset-edit account adds itself to the immutability
      bypass list, deletes the tag, and removes that entry in the same
      session, and both steps are written into the rollback note here; the
      tag-pushing account then pushes the replacement tag), the acceptance
      checklist from M1–M3,
      and the note that `workflow_dispatch` needs the workflow on the default
      branch but runs the selected ref's copy. It opens with a `Last reviewed:`
      marker — `REQUIRED_FILES` turns a missing marker into a hard hook error.
      Add it to `REQUIRED_FILES` in `hooks/scripts/check_doc_freshness.py`,
      update the hook's error text (it lists the required paths), and add it
      to the durable-doc list in `dev-docs/README.md`.
- [x] Rehearse first: run the workflow with `workflow_dispatch` (the
      `release.yml` bullet above). A dispatch runs `check-hooks`,
      `check-test`, `check-audit` and, only if those pass, `build-macos`. It
      skips `sign-macos` and `publish`: no `release` environment and no
      secrets. On a dispatch the check jobs are the pre-commit gates, the
      full pytest matrix and the dependency audit; the tag-equals-version
      requirement stays tag-push only (Decision 9).
      `workflow_dispatch` requires the workflow on the default branch, so this
      is available once `release.yml` is merged to `main`. A dispatch is
      accepted only on `refs/heads/main` (amended 2026-11-18): `check-hooks`
      fails any other ref and `build-macos` is guarded on the ref, so a branch
      cannot be rehearsed. Pushing a tag is what creates the draft
      release, so a rehearsal tag would not do.
      Then the first real run at the next version bump; v0.1.0 stays
      source-only.
      Passed 2026-11-19 (run 44590496069, `main` at `8f9a814`):
      `check-hooks` (including the interpreter-pin check), `check-test`
      (all four cells), `check-audit` and `build-macos` are green;
      `sign-macos` and `publish` are skipped as designed. This also answers
      the round-5 open question: `build.py`'s `tkinter.Tk()` preflight runs
      on the headless macOS runner. The first attempt (run 44573815905)
      failed the pin check because `setup-uv` 0.12.24 could not install
      `BUILD_PYTHON` 3.13.17; the pin is now the one `.github/uv.toml` read
      through `version-file`. Signing, notarization and publishing stay
      unticked until the first tag run.
- [ ] Manual acceptance (from M2 on, in a clean Standard second account or VM
      with no user-installed Python on `PATH`; Apple's `/usr/bin/python3` may
      be present): download the drafted release asset fresh (the browser sets
      the quarantine flag), open the DMG, drag to Applications, launch, create
      an archive with a generated password, open it in Finder and 7-Zip.
      Record the date, macOS version and which `python3` was visible here.
      Accepted as an M2 deviation 2026-11-19 (macOS 26 / darwin 25.6.0, DMG
      SHA-256 `9da7a00b7e64e8692c7204312800590f464e4d3a5825682cc572699c8f733b8e`):
      the signed/notarized draft was installed in the Standard `test` account;
      Finder launch, generated-password archive creation and archive opening
      succeeded. The login shell saw Homebrew `/opt/homebrew/bin/python3`
      (3.14.7) through `/etc/paths.d/homebrew`; unadorned `python` was absent.
      The Finder-launched app's own `PATH` and Python/Tcl environment were not
      separately measured, so the literal no-user-installed-Python-on-`PATH`
      condition was not established. Static inspection found bundled
      Python/Tcl/Tk, only system or bundle-relative direct Mach-O
      dependencies, and no first-party external-interpreter invocation. The
      maintainer accepted this as a deviation for the v0.2.0 draft; the
      strict box stays unticked for a future clean-VM recheck.

## Phase 3 — Windows app

> **Deferred 2026-11-21.** The core is POSIX-only (`O_DIRECTORY`,
> `O_NOFOLLOW`, `dir_fd` and `os.fwalk` in `collect.py`, `sources.py`,
> `verify.py` and `output.py`), so the Windows app launches but fails when
> Start is pressed. PR #26 is the draft build half; it must not publish or
> attach a Windows artifact until the filesystem backend and Windows tests
> land. Phase 4 Linux proceeds first. See
> [the port plan](2026-11-21-windows-core-port.md),
> [the investigation](../investigations/2026-11-21-windows-core-portability.md)
> and the Greptile P1 on PR #26.

- [ ] Build the onedir zip unsigned in `build-windows` (both triggers, no
      environment, uploads the zip) on a versioned Windows label
      (`windows-2025`, or `windows-2022` if that image is what the plan
      offers when this phase lands — decide then; never `windows-latest`)
      with the uv-managed Python; embed the exe icon and the file version
      resource. Runner and image bumps follow Decision 6.
- [ ] CI smoke: extract the uploaded
      `zipseal-gui-<version>-windows-x64.zip` into a fresh directory, launch
      `zipseal-gui.exe` from that extraction, and verify the archive path:
      create an archive with a generated password, decrypt it, and open it.
      Running the exe from the build tree does not count, and a launch-only
      smoke does not pass. Wait, confirm the process is alive, stop it. A
      failure fails the job.
- [ ] Manual acceptance (drafted release, on a clean Windows 11 VM under
      Parallels/UTM, where the x64 zip runs under emulation on
      Windows-on-ARM): download the zip, unzip, run `zipseal-gui.exe`, create
      an archive with a generated password, and open it in 7-Zip (Explorer's
      built-in zip support is unreliable for AES; see
      `user-docs/opening-archives.md`). Record the date and Windows version
      here.
- [ ] Resolve signing (Decision 3) on both tracks:
  - SignPath Foundation application — only after the first tagged release has
    shipped the (unsigned) zip: SignPath requires the project to be already
    "released in the form that should be signed", and the application needs
    the Releases-page download URL. Add the required "Code signing policy"
    section to `README.md` with their exact wording (re-verify the sentence
    against signpath.io at application time; the 2026-11-02 snapshot is
    "Free code signing provided by SignPath.io, certificate by SignPath
    Foundation"), list committer/approver roles, then apply with the
    repository and download URLs. If approved, integrate their GitHub Action
    (pinned by SHA) into a separate `sign-windows` job — tag-only `if`,
    `environment: release`, and no rewrite of `build-windows`. It extracts
    `zipseal-gui.exe` and the bundled DLLs from the uploaded zip,
    Authenticode-signs them all, repacks the zip, and fails unless `signtool
    verify /pa /v` passes on the exe extracted from the final zip. It then
    extracts that repacked zip into a fresh directory and runs the same
    archive-create/decrypt smoke from there, and uploads only the repacked
    zip. Running the exe from the build tree does not count, and a launch-only
    smoke does not pass. Keep per-release approvals in mind.
  - Store MSIX spike: free individual Partner Center account, package the
    onedir as a full-trust MSIX, submit once, confirm Microsoft re-signing
    removes SmartScreen warnings. Decision after the spike; do not commit to
    the Store before it passes certification once.
  - Guidance that outlives signing: keep the "More info → Run anyway" steps
    for every zip until a signed release is observed warning-free on a clean
    Windows machine — a new signature has no SmartScreen reputation, so a
    signed build can still warn. Document the verified-publisher variant.
    Smart App Control may still block the unsigned zip outright; submit AV
    false positives to Microsoft's portal.
  - What Store signing covers: the Store re-signs only the MSIX it
    distributes. If that is the route that lands, `zipseal-gui.exe` in the
    downloadable zip stays unsigned and keeps the guidance above; only
    SignPath (or a purchased certificate) Authenticode-signs that executable.
- [ ] Optional, deferred until asked: Inno Setup installer (the portable zip is
      the artifact this plan promises) and a winget manifest PR.

## Phase 4 — Linux app

- [x] `build-linux` uses `runs-on: ubuntu-24.04` and
      `container: image: ubuntu@sha256:<digest>`, the digest of `ubuntu:22.04`
      recorded in `dev-docs/releasing.md` when this phase lands (glibc 2.35;
      the PyInstaller bootloader needs 2.17+ — neither is the shipped floor).
      A direct run on the `ubuntu-24.04` label would be glibc 2.39 and would
      throw away the container. Runner and digest bumps follow Decision 6.
      After the build, read the glibc requirement from the bundled Python,
      Tcl/Tk and extension modules (Risk 8) and record it in the release
      notes. Produce the onedir tree, then an AppImage via a pinned
      `appimagetool`, and pack the onedir as one top-level directory with the
      binary at mode `0755`: `tar -czf
      dist/<version>/zipseal-gui-<version>-linux-x86_64.tar.gz -C
      dist/<version> zipseal-gui`. `appimagetool` is itself a Type 2
      AppImage and will not run inside an unprivileged
      container without `/dev/fuse`, so extract it first
      (`./appimagetool-x86_64.AppImage --appimage-extract`) and invoke
      `ARCH=x86_64 ./squashfs-root/AppRun dist/<version>/AppDir
      dist/<version>/zipseal-gui-<version>-linux-x86_64.AppImage`. Name the
      output explicitly: appimagetool otherwise derives it from the AppDir
      name and drops the version. Fetch `appimagetool` into `build/tools/`
      (gitignored) with a pinned checksum. Assert the built AppImage is
      executable before upload; `publish` runs `chmod +x` again, because the
      artifact store drops the bit (the hash is of the bytes). The container
      needs `file`, `binutils`
      (PyInstaller shells out to `objdump`/`objcopy`), `libc-bin` (`ldd`),
      `desktop-file-utils`, plus `xvfb`/`xdotool` for the smoke test below.
- [x] AppDir contents: `zipseal-gui.desktop` (`Terminal=false`,
      `Categories=Utility;Security;`), `AppRun`, generated icon.
- [x] CI smoke under `xvfb-run`, both artifacts. The AppImage has no FUSE
      here: `./zipseal-gui-<version>-linux-x86_64.AppImage
      --appimage-extract-and-run` (or `--appimage-extract`, then
      `./squashfs-root/AppRun`). For the archive, extract
      `dist/<version>/zipseal-gui-<version>-linux-x86_64.tar.gz` into a fresh
      directory and launch `<fresh>/zipseal-gui/zipseal-gui`. Running
      `dist/<version>/zipseal-gui/zipseal-gui` in the build tree does not
      count. Wait until the process is alive, and if practical assert a
      window named
      `zipseal` (`xdotool search --name`), then terminate. Run
      `desktop-file-validate` on the AppDir desktop file. A failure fails
      the job.
- [ ] Manual acceptance (drafted release, in a Linux VM with no system
      Python): download the AppImage and the `.tar.gz`; extract the `.tar.gz`
      and run the binary; run the AppImage (use
      `--appimage-extract-and-run` if FUSE is unavailable); create an archive
      with a generated password, and open it in 7-Zip or `bsdtar`. Record the
      date and distro here.
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
- [ ] `SPEC.md`: replace the "planned, not implemented" note added with this
      plan (`SPEC.md:112`, "Planned, not implemented") with the artifact table above; the GUI ships
      frozen while the CLI stays source-installable.
- [ ] `CHANGELOG.md` (user-visible) and `CHANGELOG.dev.md` (workflow internals);
      doc-gardening pass; bump `Last reviewed` dates after re-reading.

## Phase 6 — CLI on PyPI (optional, decide after M3)

- [ ] `uv build` and publish via PyPI Trusted Publishing (`id-token: write`,
      `pypi` environment). The gate is that environment's required reviewer.
      `workflow_dispatch` only starts the job; it is not a second path that
      skips the approval. Never publish implicitly on a tag, because PyPI
      versions are immutable and a re-cut tag cannot re-upload. Name
      `zipseal` is free (checked 2026-11-02).
- [ ] README: `uvx zipseal` as the one-line CLI install.
- [ ] Only worth doing if installing the CLI without a git URL is wanted; it
      changes nothing for GUI users.

## Test list

Each behavior gets a pytest test per repo convention. Packaging tests:

- [x] `read_version()` returns `pyproject.toml`'s version; a version
      substitution render (Info.plist fields, Windows version resource string)
      contains it.
- [x] The artifact globs (`*.dmg`, `*.msi`, `*.exe`, `*.AppImage`, `*.tar.gz`)
      are present in `.forbidden-paths` and the output roots (`dist/`, `build/`)
      are ignored by `.gitignore`. Exercise
      `hooks/scripts/check_forbidden_paths.py` the way
      `tests/test_check_pins.py` exercises its hook
      (`importlib.util.spec_from_file_location`), or run its `main()` against a
      `tmp_path` repo root: a synthetic tracked artifact under `dist/` must be
      rejected. Never `git add` into the real index from a test.
- [x] `packaging/linux/zipseal-gui.desktop` has `Name`, `Exec`, `Icon`,
      `Terminal=false`, sorted `Categories`; `AppRun` is tracked executable.
- [x] `packaging/macos/entitlements.plist` parses with `plistlib` and
      contains only keys Decision 4 lists with the failure that required them
      (an empty plist passes).
- [x] `collect_data_files()` returns both `("src/zipseal/icon.svg", "zipseal")`
      and `("build/icons/icon.png", "zipseal")`. No PNG is committed (`*.png`
      is forbidden); if the function requires the file to exist, the test
      creates one under `tmp_path`.
- [x] `tests/test_window_icon.py` replaces
      `test_set_icon_falls_back_when_svg_is_unreadable`. Monkeypatch
      `gui_view.ICON` (the name that module imported, not `gui.ICON`) at a
      `tmp_path` SVG that has a sibling PNG. Raise `TclError` only for the
      SVG format and the PNG loads → the icon is set from the PNG. Both fail
      → returns False, Tk's default icon remains, and launch is unaffected.
      Patching every `PhotoImage` call does not count as the PNG case. Both
      cases keep `@pytest.mark.gui` and `pytest.importorskip("tkinter")`, like
      the test they replace, and run with `uv run pytest -m gui
      tests/test_window_icon.py`.

CI smoke gates (not pytest): the per-platform launch checks run against the
artifact the workflow uploads; Windows and Linux fail the job, and the macOS
launch check may be advisory (its job still gates on `codesign`/`spctl`/
`stapler`). Manual acceptance of the drafted artifact on a machine without
Python, dated per platform here, is the blocking gate for publish.

## Secrets to set up (names only)

`APPLE_CERT_P12` (base64 Developer ID Application .p12), `APPLE_CERT_PASSWORD`,
`APPLE_TEAM_ID`, `APPLE_API_KEY_ID`, `APPLE_API_ISSUER_ID`,
`APPLE_API_PRIVATE_KEY` (base64 .p8). The ephemeral keychain password is
generated per run with `openssl rand`, not stored (amended 2026-11-18).
All Apple secrets live in the protected `release` environment (deployment
limited to `v*` tags). The reviewer split is the one in the `release.yml`
bullet: a second account, Prevent self-review on, administrator bypass off.
Rehearsals run without the secrets. `SIGNPATH_*`
only if Phase 3 signing is approved. Linux needs no secrets, and
`dev-docs/releasing.md` documents origin and rotation.

## Risks and open questions

1. **SignPath acceptance is not guaranteed** (project must be "released",
   documented, OSI-licensed, and it needs a code-signing policy page and
   approver roles). If declined: stay unsigned with documentation, or pursue
   the Store spike. Neither path costs money, which is the point of Decision 3.
2. **Store MSIX effort is unknown** for a PyInstaller onedir app (full-trust
   packaging, Store certification). The spike is deliberately time-boxed.
3. **Notarization surprises**: the first submission may need an entitlement
   (Tk/PyInstaller). Budget a few iterations; each added entitlement needs
   its failure recorded in Decision 4. Every future release must stay signed
   and stapled or user trust breaks.
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
  smoke-tested in CI and accepted on machines with no user-installed Python on
  `PATH` (macOS: a clean VM or Standard second account, not the dev account
  where `uv` and its managed interpreters live; Apple's `/usr/bin/python3` may
  be present; Windows: a clean Windows 11 VM under Parallels/UTM, where the
  x64 zip runs emulated on Windows-on-ARM; Linux: a VM with no system Python),
  `SHA256SUMS` + attestations attached; the
  Windows signing outcome is recorded per artifact (zip signed, or zip
  unsigned with the Store MSIX signed separately).
- **M4**: README, `user-docs/`, `AGENTS.md` and `SPEC.md` updated;
  `dev-docs/releasing.md` finalized (created and freshness-hooked in Phase 2);
  PyPI decision recorded.

## Review changes

- 2026-11-02: An antigravity/gemini-3.8-flash-high review (4 blockers, 6
  majors, 6 minors): pre-populated entitlements, `ditto` before `notarytool`,
  the keychain fix, extracting appimagetool, `spctl -t open`, `*.tar.gz` in
  the globs, `releasing.md` in the freshness hook, phases re-aligned to
  milestones, `run_gui.py`, uniform artifact names, icons in `build/icons/`.

- 2026-11-03: Two self-reviews: Decision 5 gained `*.tar.gz`; Phase 0 stopped
  contradicting Decision 4; a glued checkbox and a broken code span were
  fixed; CI smoke and draft-release acceptance moved from M1 to Phase 2; the
  Linux container list was corrected; `release.yml` became macOS-only at M2;
  M4 aligned with `releasing.md`; Phase 3 became two tracks; entitlements
  softened; PyPI gated; version identification documented; arm64 deferred.

- 2026-11-04: CodeRabbit (twice) and agy/gemini: the tag check compares the
  whole tag and skips on dispatch; `workflow_dispatch` cannot publish; the
  contract matches the gates (CI smoke advisory on macOS only, per-platform
  manual acceptance); glibc 2.17 is the bootloader floor only; signing paths
  use `dist/<version>/`; Windows acceptance opens in 7-Zip; Risk 8 measures
  the real floors.

- 2026-11-10: CodeRabbit, Greptile and Sourcery: entitlements start empty and
  need a recorded failure; the Apple secrets sit behind a protected
  environment; `publish` groups per tag and asserts the tag's commit; the
  acceptance gate names only the platforms a release contains; Store signing
  is separated from the unsigned zip and SmartScreen guidance outlives
  signing; M1 expects the Gatekeeper block; versioned runners; Tk preflight;
  a marked `SPEC.md` note.

- 2026-11-11: CodeRabbit (two passes): SignPath signs the exe inside the zip
  and the job verifies it; signing requires the push event as well as a `v*`
  ref; `publish` checks the remote tag (peeled `^{}` for annotated tags, the
  tag ref for lightweight ones), passes `--verify-tag`, and relies on a `v*`
  tag ruleset; tag creation is limited to maintainers who are not approvers,
  with self-review prevented.

- 2026-11-11: A Step 5 Preview (NVIDIA) review, three passes: split signed
  and unsigned work into `build-macos`/`sign-macos` (`environment` is
  job-level only and a `v*` rule fails a branch run) and gave Windows the
  same `build-windows`/`sign-windows` split; `packaging/` joins basedpyright
  and ruff's ignores; the keychain imports the `.p12` before the partition
  list; the `.app` is archived for the build/sign transfer; icon `datas`,
  toolchain and Python-free M3 hosts are settled; tests never touch the real
  index; the interpreter pin and `workflow_dispatch` semantics are explicit;
  `stapler validate` joins the gate; the log is condensed.

- 2026-11-12: CodeRabbit: a dispatch rehearses `check` and `build-macos`
  (the tag check stays tag-push only) and still skips signing and
  `publish`; the `release` approval names the second-account control and
  says the guarantee does not hold without it; nested Mach-O is signed
  inside out before the outer bundle; Phase 0 tasks the PNG fallback and
  its two acceptance cases.

- 2026-11-12: Step 5 Preview (NVIDIA), one pass. The four CodeRabbit edits
  stood. `publish` now `needs` the gates that produce shipped bytes, and
  `check` re-runs `ci.yml` because a tag push does not. Phase 2 creates the
  `release` environment and the `v*` ruleset before any secret is stored.
  Nested signing skips Mach-O object files, and the Developer ID identity
  is gated before notarization. The PNG tests use a `tmp_path` icon and a
  selective SVG failure. Linux smoke names both artifacts and the FUSE-less
  launch; the container image is digest-pinned on `ubuntu-24.04`.

- 2026-11-12: CodeRabbit: `check-test` is `ci.yml`'s Linux/macOS × Python
  3.11/3.13 matrix, with the archive-tool setup, and `publish` needs every
  cell plus the pre-commit and audit jobs. Tag creation and tag immutability
  are separate rulesets; the tag-pushing account bypasses only creation.
  The Linux smoke extracts the shipped `.tar.gz` into a fresh directory.

- 2026-11-12: Step 5 Preview (NVIDIA). The three CodeRabbit edits stood.
  Rollback adds a temporary immutability bypass and removes it in the same
  session, before the tag-pushing account re-tags. `check-test` copies the
  CI test job. Superseded 2026-11-16: see round 2, and `build-macos` waits on the check jobs so
  a red gate never starts signing. Windows smoke extracts the shipped zip.
  The Linux archive is one `zipseal-gui/` directory with the binary at
  `0755`.

- 2026-11-12: Self-review. `check-hooks` copies `ci.yml`'s `checks` job,
  including `uv sync --locked`, which the basedpyright hook needs
  (superseded 2026-11-16: see round 2).
  `sign-macos` uploads the signed DMG that `publish` collects.
  Step 5 Preview (NVIDIA) then confirmed both edits. `publish` downloads
  shipped artifacts by name. The PNG tests stay `gui`-marked. The `SPEC.md`
  and `TODO.md` references and the `packaging` shadowing reason were
  corrected.

- 2026-11-16: Muse Spark 1.3 and Step 5 Preview reviews of the Phase 2 draft
  (both CHANGES REQUESTED). Fixes applied: job-level `actions` scope on the
  artifact jobs (upload/download needs it), macOS bash 3.2 compatibility in
  the nested-signing loops (`find -d` + `read -d ''`, `mapfile` removed), a
  corrected Developer-ID guard (`|| true` and the identity list printed), the
  DMG-mounted app re-validated (`stapler`/`codesign`/`spctl`), `build-info.json`
  checksummed and attached to the release, the `.p12`/`.p8` deleted after use,
  ephemeral-keychain search list restored on exit, `publish` pinned to
  `ubuntu-24.04`, and `git ls-remote` passed both `ref` and `ref^{}`. The
  environment/rulesets exist (created under a `kgforais1` PAT; `kgrizz-git`
  lacks admin); the maintainer then edited the environment in the UI, so the
  two-account split is currently a convention, recorded in
  `dev-docs/releasing.md`. `publish`'s tags stay tag-push activated; the
  draft-only release path is unchanged.

- 2026-11-16 (round 2): SonarCloud (S8541/S8544) and CodeRabbit findings applied
  to the Phase 2 draft PR (#20). The `check-hooks` and `check-test` sync steps
  use `--locked --no-build --no-install-project`, so those syncs build no
  wheel and install no zipseal wheel; the dependencies still install, and
  zipseal is imported from `src/` via `PYTHONPATH` in the fast suite. That
  no-PEP-517-backend guarantee is limited to those syncs: any hook not given
  those flags — currently `check-pins` and `basedpyright` — re-runs `uv run`,
  which re-syncs and can build and install the project through `uv_build`
  (`uv_build` resolves from the `build-system.requires` range, not `uv.lock`).
  The ephemeral keychain idle lock is raised with
  `security set-keychain-settings -lut 3600` so it survives notarization.
  The environment now carries both `v*` deployment policies (`branch` and
  `tag`); a branch policy alone does not match tag refs. The plan's
  environment/ruleset box stays unticked: the separate tag-pushing and
  reviewer-account control does not hold after the maintainer's UI change, and
  it needs a deliberate decision (restore the settings, or explicit acceptance
  of a single-account control). (Superseded 2026-11-17: one-account control
  accepted; see the next entry.) The secret-storage prerequisite is recorded as
  "after protection review, before the first tag", not blocked on a draft
  acceptance, because `sign-macos` itself needs the secrets.

- 2026-11-17: The maintainer explicitly accepted the one-account control for
  the `release` environment (both accounts are theirs): reviewers
  `kgforais1`/`kgrizz-git`, `prevent_self_review` off, `can_admins_bypass` on.
  The plan's environment/ruleset box is ticked on that acceptance; the
  two-account split is no longer required for the approval to count. The
  `v-tag-immutability` ruleset (empty bypass list) remains the structural
  control and is unchanged. `dev-docs/releasing.md` records the accepted
  state.

- 2026-11-18: Sourcery and CodeRabbit findings on PR #20 resolved.
  `sign-macos` now fails before any secret is read unless the tagged commit is
  an ancestor of `origin/main`. A `workflow_dispatch` is accepted only on
  `refs/heads/main`; this replaces the "Rehearse first" box's "a dispatch can
  select another ref" wording. `check-audit` exports the `build` group too.
  `check-hooks` fails if `env.BUILD_PYTHON` differs from `packaging/build.py`'s
  constant. Every tomllib/build.py Python step runs on the pinned
  `BUILD_PYTHON` via `uv run --no-project`; `publish` keeps ubuntu-24.04's
  Python 3.12 for a script without tomllib. Secret decoding uses `base64 -d`,
  which macOS and GNU both accept. The DMG mountpoint is created before
  `hdiutil attach`. The signature gate changed: `stapler validate` runs on the
  DMG and the unmounted stapled app; the mounted app gets `codesign --verify
  --deep --strict` and `spctl --assess -t exec` only, because `hdiutil` can drop
  the staple xattr. `publish` reuses an existing draft and replaces its assets
  with `--clobber`, and refuses a published release. SPEC.md now says the macOS
  DMG path is implemented (draft-only, pending M2 acceptance) and Windows and
  Linux remain planned. `releasing.md` qualifies the `v-tag-immutability`
  guarantee: it holds only while the ruleset is active, not against an actor
  who can edit or disable it. Declined: the argv finding for
  `KEYCHAIN_PASSWORD`/`APPLE_CERT_PASSWORD`, because `security` has no stdin
  path. The accepted-risk wording in `releasing.md` is that a same-user
  process on the runner could read the two passwords from the process table
  while a `security` call runs, and that neither password is useful outside
  the job.

- 2026-11-18 (round 2): Hyrax findings on PR #20 applied. The `publish`
  checkout sets `persist-credentials: false`. `build-macos` and `sign-macos`
  drop `actions: write` and `publish` drops `actions: read`, because
  same-run artifact transfer uses `ACTIONS_RUNTIME_TOKEN`; the main-only
  dispatch guard stays as a second check. The release notes pin the CLI
  install line to the tag. The TeamIdentifier gate fails on an empty
  `APPLE_TEAM_ID` and matches the whole line. Separately, the keychain
  password is generated per run with `openssl rand -base64 32` and masked, so
  the `KEYCHAIN_PASSWORD` secret is retired; its argv exposure now reveals
  nothing outside the job. `APPLE_CERT_PASSWORD` remains the one argv
  exception.

- 2026-11-18 (round 3): CodeRabbit findings applied. Immutable releases were
  enabled on the repository (owner PAT), so `publish`'s draft-reuse path cannot
  replace the assets of a release published mid-run. Immutable releases do not
  lock title or notes, so the path uploads assets first and re-checks `isDraft`
  before editing the notes; a publish inside that last gap could still
  overwrite title and notes, never assets. `releasing.md` now says a same-user process that captures
  `APPLE_CERT_PASSWORD` from argv could also copy `cert.p12` during import and
  sign off-runner until the certificate is revoked, with revoke-and-rotate as
  the response. The stale `actions: write` claim was removed from the dispatch
  section.

- 2026-11-18 (round 4): CodeRabbit noted that `--clobber` deletes an asset
  before re-uploading it, so publishing during a re-run can leave a published,
  immutable release missing an asset. `releasing.md`'s tag-to-release steps
  now require every run for the tag to finish before acceptance, a check of
  the draft's final assets, and no re-run during acceptance or publication.
  A follow-up CodeRabbit note added the recovery path: if the asset check or
  acceptance fails, abort, leave the draft unpublished, re-run, wait for it to
  finish, and repeat every final check before publishing.

- 2026-11-18 (round 5): DeepSeek review of PR #20. `releasing.md` step 1 now
  runs `uv lock` with the version bump (the lockfile records the project
  version) and lands it on `main` through a PR (the `main` ruleset requires
  one). The three `upload-artifact` steps set `overwrite: true` so a full
  re-run does not fail on an existing artifact name. The stale "no Apple
  secrets stored" text in this plan and `CHANGELOG.dev.md` and the CI signing
  box's stored `KEYCHAIN_PASSWORD` were corrected. Open, untested: whether
  `build.py`'s `tkinter.Tk()` preflight runs on the headless macOS runner; the
  first dispatch rehearsal answers it.

- 2026-11-19: CodeRabbit asked `releasing.md` step 7 to separate transient
  failures (re-run, repeat steps 5 and 6) from deterministic app defects. A
  re-run rebuilds the same commit, so a defect means deleting the draft,
  fixing it on `main` through a PR, and cutting a new version (re-tagging the
  same version goes through Rollback and is not preferred).

- 2026-11-19 (round 2): Hyrax noted that a tag push runs `release.yml` from the
  tagged commit, so the on-main ancestry check cannot keep secrets from a tag
  pusher who edits the workflow. The workflow comments and `releasing.md` now
  call it defence in depth against mis-tagging. They name the `release`
  environment (deployment policy and reviewers) and the tag rulesets as the
  secrets boundary, and the reviewer confirms the commit is on `main` before
  approving `sign-macos`. This corrects the 2026-11-18 entry's framing.

- 2026-11-19 (round 3): The first `workflow_dispatch` rehearsal (run
  44573815905) failed `check-hooks` "Build interpreter pins agree": uv
  0.12.24 cannot install `BUILD_PYTHON` 3.13.17 (its embedded manifest
  stops at 3.13.16), which also breaks `build-macos`/`sign-macos`'s
  `uv run --python 3.13.17`. All `setup-uv` pins move to 0.13.9, which
  installs 3.13.17 and still satisfies `uv_build<0.14.0`. The macOS
  `check-test` cells were cancelled by GitHub runner capacity, not by the
  change. The rehearsal box stays unticked until a green dispatch.

- 2026-11-19 (round 4): The uv pin is centralized in `.github/uv.toml`
  (`required-version = "==0.13.9"`); every `setup-uv` step passes
  `version-file: .github/uv.toml`, so a bump is one line. `check-pins` now
  accepts the version-file form only when it names that file, validates the
  file's exact `required-version`, and rejects a step that sets both
  `version` and `version-file`.

- 2026-11-19 (rehearsal): The first green `workflow_dispatch` (run
  44590496069, `main` at `8f9a814`) passed `check-hooks`, `check-test`,
  `check-audit` and `build-macos`; `sign-macos` and `publish` were skipped
  as designed. The headless macOS runner accepts `build.py`'s
  `tkinter.Tk()` preflight, closing the open question in the 2026-11-18
  round-5 entry. The rehearsal box is ticked; the signing, notarization
  and publish boxes stay unticked until the first tag run.

- 2026-11-19 (acceptance): The "no Python on `PATH`" gate now means no
  user-installed Python (uv-managed, pyenv or Homebrew). The Apple-provided
  `/usr/bin/python3` may be present: it ships with the OS and is not a user
  install. A clean Standard second account is the macOS clean environment,
  as M3 already allowed, so acceptance needs no separate hardware; the
  maintainer has no Python-free machine. The acceptance record names the
  visible `python3`.

- 2026-11-19 (M2 acceptance deviation): The v0.2.0 signed/notarized draft
  passed the Finder launch and archive workflow in the Standard `test`
  account, but that account's login shell saw Homebrew
  `/opt/homebrew/bin/python3` (3.14.7) through `/etc/paths.d/homebrew`;
  unadorned `python` was absent. The Finder-launched app's own PATH was not
  separately measured, so the literal no-user-installed-Python condition was
  not established. Static inspection (47 Mach-O files, source search) found
  bundled Python/Tcl/Tk, only system or bundle-relative dependencies, and no
  first-party external interpreter. The maintainer accepted the deviation
  for v0.2.0; the strict acceptance box stays unticked for a future clean
  VM.

- 2026-11-20 (v0.2.0 tag run): Tag `v0.2.0` on `main` at `87e1f5d` ran
  `release.yml` as run 44629800543. All five check jobs, `build-macos`,
  `sign-macos` and `publish` succeeded. `sign-macos` passed the on-main
  ancestry check, the ephemeral-keychain and Developer ID steps, nested
  signing, notarization/stapling and the `codesign`/`stapler`/`spctl` gate.
  `publish` verified the tag, wrote `SHA256SUMS`, attested the artifact and
  the sums, and created the draft. The five Phase 2 boxes above are ticked;
  the strict manual-acceptance box stays unticked under the 2026-11-19 M2
  deviation.

- 2026-11-21 (Windows deferral): PR #26's `build-windows` job and spec were
  reviewed clean, but Greptile found the core is POSIX-only
  (`O_DIRECTORY`/`O_NOFOLLOW`/`dir_fd`/`os.fwalk` in `collect.py`,
  `sources.py`, `verify.py`, `output.py`); the Windows app launches but fails
  on Start. An NVIDIA-hosted Kimi K3.1 Pro review estimated 15–26 person-days
  (3–5 focused weeks) for production parity, recommended a small filesystem
  backend abstraction and a `windows-2025` core matrix, and rejected a weak
  stdlib prototype under the current security claims. PR #26 is a draft;
  Phase 4 Linux proceeds first. See
  [the investigation](../investigations/2026-11-21-windows-core-portability.md).

- 2026-11-22 (Linux rehearsal): Run 45077481075 on `main` at `a8bfb92`
  passed the check jobs, `build-macos` and `build-linux`; `sign-macos` and
  `publish` were skipped as designed. `build-linux` built the AppImage and
  tarball, both smoke tests found the `zipseal` window, and
  `build-info-linux.json` reports `GLIBC_2.35`, Tk 9.0, Python 3.13.17 and
  PyInstaller 6.22.3. The tag's `publish` job appends this file to the
  release notes. The Phase 4 build, AppDir and smoke boxes are ticked; the
  manual-acceptance and Linux-docs boxes remain.
