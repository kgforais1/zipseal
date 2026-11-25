# Releasing zipseal-gui

Last reviewed: 2026-11-23

The operator's runbook for the frozen GUI apps. The design and the phase order
are in
[`dev-docs/plans/2026-11-02-gui-executables.md`](plans/2026-11-02-gui-executables.md);
this file is the copy you follow when cutting a release. The CLI stays
source-installable from GitHub with `uv tool install`; only the GUI is shipped
as a downloaded app.

## Accounts

| Role | Account |
|---|---|
| Pushes `v*` tags; the only bypass of the creation ruleset | `kgrizz-git` |
| Edits the rulesets | `kgforais1` |

Both accounts are the maintainer's; the return of a genuine second-person
control is a maintainer decision, not assumed here. As of 2026-11-17 the
one-account control is accepted; see the environment section.

The repository owner is also the tag-pushing account's operator: both accounts
belong to the same person. As of 2026-11-16 the owner changed the required
reviewer list and turned `prevent_self_review` off in the UI, and on 2026-11-17
explicitly accepted the one-account control: the `release` environment is
reviewed by the maintainer in whatever review list the owner keeps it in, and
the tag-pushing account is the maintainer. The recorded settings (reviewers
`kgforais1` and `kgrizz-git`, `prevent_self_review` off, `can_admins_bypass`
on) are the accepted state, not an oversight. The `v-tag-immutability` ruleset
(empty bypass list) is the remaining structural control: while the ruleset is
active it blocks an accidental or malicious tag move regardless of account. It
does not stop an actor with ruleset-editing access (the repository owner or an
admin) from changing or disabling the ruleset and then moving the tag; that
residual risk rests on the owner account's own security. If the owner later
restores the two-account split, update this section and the plan's Phase 2 box
text, and tick it as restored-and-verified instead of accepted.

## Repository protections

### `release` environment

**Live state as of 2026-11-16** (created 2026-11-16T04:28:29Z):

- Deployment policies: custom `v*` policy of type `branch` (created 2026-11-16)
  followed by a custom `v*` policy of type `tag` (added the same day; a
  branch-only policy does not apply to tags).
- Required reviewers: **`kgforais1` and `kgrizz-git`** — the repository owner
  changed the required reviewer list in the UI, with both accounts being the
  maintainer's. The intended split no longer holds; the maintainer accepted
  the one-account control on 2026-11-17.
- Prevent self-review: **off** (accepted; see above).
- Allow administrators to bypass: **on**. The environments REST API has no
  body parameter for this (`wait_timer`, `prevent_self_review`, `reviewers`,
  `deployment_branch_policy` only), so it cannot be verified or set from a
  script. To turn it off: Settings → Environments → `release` → uncheck
  "Allow administrators to bypass".
- Wait timer: 0.
- Immutable releases: **on** (enabled 2026-11-18 with the owner PAT). A
  published release's assets and tag cannot change; its title and notes can,
  and drafts stay fully editable.
  Verify with `gh api repos/kgforais1/zipseal/immutable-releases` (owner token).
- Secrets: the six Apple secrets below were stored on 2026-11-18. A seventh,
  `KEYCHAIN_PASSWORD`, was stored the same day and deleted later that day: the
  workflow now generates the keychain password per run.

`environment` is job-level, so only `sign-macos` requests it. `build-macos` runs
on both triggers with no environment and no secrets; a `workflow_dispatch`
cannot reach the secrets because `sign-macos` is event-guarded. Before any step
reads a secret, `sign-macos` checks out full history and fails unless the tagged
commit is an ancestor of `origin/main`. That check guards against mis-tagging
only. A tag push runs `release.yml` as it exists at the tagged commit, so a tag
on a commit whose workflow drops the check would skip it. The secrets boundary
is this environment's `v*` policy and required reviewers, plus the tag
rulesets. Before approving `sign-macos`, the reviewer confirms that the run's
commit is on `main`.

### Tag rulesets

| Ruleset | Target | Rules | Bypass actors |
|---|---|---|---|
| `v-tag-creation` | `v*` tag | `creation` | `kgrizz-git` (User, always) |
| `v-tag-immutability` | `v*` tag | `update`, `deletion` | none |

Creation and immutability are separate. The tag-pushing account can create a tag
and cannot change or remove one. The immutability bypass list is empty, so no
actor — including the owner — can edit or delete a `v*` tag while the ruleset is
active. See [Rollback](#rollback) for the temporary-bypass procedure.

### How these were created

`kgrizz-git` has push but not admin, so the environment and rulesets were
created with a fine-grained PAT owned by `kgforais1` (the owner): repository
access limited to `kgforais1/zipseal`, `Administration: Read and write`. The
token lives in a gitignored `.env.gh.PAT` and is used per-command via
`.context/gh-pat.sh` (`GH_TOKEN=... gh ...`); it is never committed. The
required reviewer list and self-review flag were subsequently changed by the
owner in the UI (both accounts are the same person's), which is why the live
state above is the source of truth, not the calls.

The API calls that produced the baseline state:

```sh
# Environment: custom v* deployment policy, reviewer, no self-review.
gh api --method PUT repos/kgforais1/zipseal/environments/release --input - <<'JSON'
{
  "deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true},
  "wait_timer": 0,
  "prevent_self_review": true,
  "reviewers": [{"type": "User", "id": 322685718}]
}
JSON
gh api --method POST repos/kgforais1/zipseal/environments/release/deployment-branch-policies \
  -f name='v*' -f type=branch
gh api --method POST repos/kgforais1/zipseal/environments/release/deployment-branch-policies \
  -f name='v*' -f type=tag

# Creation ruleset: only the tag-pushing account may bypass.
gh api --method POST repos/kgforais1/zipseal/rulesets --input - <<'JSON'
{
  "name": "v-tag-creation",
  "target": "tag",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["refs/tags/v*"]}},
  "rules": [{"type": "creation"}],
  "bypass_actors": [{"actor_id": 216068303, "actor_type": "User", "bypass_mode": "always"}]
}
JSON

# Immutability ruleset: no bypass actors at all.
gh api --method POST repos/kgforais1/zipseal/rulesets --input - <<'JSON'
{
  "name": "v-tag-immutability",
  "target": "tag",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["refs/tags/v*"]}},
  "rules": [{"type": "update"}, {"type": "deletion"}]
}
JSON
```

The reviewer `id` is `kgforais1`'s user id and the bypass `actor_id` is
`kgrizz-git`'s. Re-read both with `gh api users/<login> --jq .id` before
creating them; the ids are stable, but a typo here fails the approval split.

Verification commands (run read-only):

```sh
gh api repos/kgforais1/zipseal/environments/release \
  --jq '{can_admins_bypass, reviewers: [.protection_rules[] | select(.type=="required_reviewers") | .reviewers[].reviewer.login], prevent_self_review: [.protection_rules[] | select(.type=="required_reviewers") | .prevent_self_review]}'
gh api repos/kgforais1/zipseal/environments/release/deployment-branch-policies
gh api repos/kgforais1/zipseal/rulesets --jq '.[] | {id, name, target, enforcement}'
```

Creation-time checklist: confirm the numeric reviewer/bypass ids resolve to the
intended logins; confirm the `v*` deployment policies include a `branch` and a
`tag` policy (a branch-only policy does not apply to tags); confirm both
rulesets show `enforcement: active`. Store the signing secrets only after the
protection review above has passed (and after changing or accepting the
environment's reviewer/self-review settings deliberately) — they are needed to
create the first draft release. Validate the downloaded artifact before
publishing the draft, as part of the acceptance checklist below.

## Secrets

Names only. Values live in the `release` environment, which is limited to `v*`
tags and requires the reviewer above.

| Secret | Holds |
|---|---|
| `APPLE_CERT_P12` | base64-encoded Developer ID Application `.p12` |
| `APPLE_CERT_PASSWORD` | password for that `.p12` |
| `APPLE_TEAM_ID` | Apple Developer team id |
| `APPLE_API_KEY_ID` | App Store Connect API key id |
| `APPLE_API_ISSUER_ID` | App Store Connect API issuer id |
| `APPLE_API_PRIVATE_KEY` | base64-encoded `.p8` private key |

Origin: the certificate and API key come from the Apple Developer account that
already exists for this project. Rotation: re-export the `.p12` and `.p8`,
base64 them, and replace the environment secrets; no repository change is
needed. Never put a secret value in this file, a workflow, a log or a test.

**Known exception, recorded deliberately.** `security` has no stdin mechanism
for the keychain password or the `.p12` import password, and the plan prescribes
those exact commands, so the keychain password and `APPLE_CERT_PASSWORD` travel in
argv inside the (job-scoped, ephemeral-runner-scoped) `sign-macos` steps. This
is a deliberate tension with AGENTS.md's "never put a password in argv": the
values are not printed to the log, the runner is destroyed afterwards, and the
alternative (an expect-like wrapper or a passwordless keychain) would weaken
hardening rather than help. If a stdin path appears in a future `security`,
switch to it. Sourcery raised this on PR #20 (2026-11-18, "Signing credentials
appear in process arguments") and it was declined for the reason above. The
residual risk is concrete: while each `security` call runs, another process on
the same runner, running as the same user, could read the passwords from the
process table. The keychain password is generated per run and guards a keychain
deleted at the end of the job, so leaking it reveals nothing. The `.p12`
password is different. A same-user process that captures it from argv could
also copy `cert.p12` while it sits on disk during import. That pair can be
taken off the runner and used to sign as the Developer ID until the
certificate is revoked. The mitigation is that only this job's own steps run on
the runner, and only after the tagged commit is verified on `main`; a
compromised dependency running in those steps could equally read the secrets
from its environment. If this exposure is suspected, revoke the certificate and
rotate `APPLE_CERT_P12` and `APPLE_CERT_PASSWORD`. The `.p12` and `.p8` reach
disk through stdin, never argv, and are deleted after use.

## Tag to release

1. Bump `version` in `pyproject.toml`, run `uv lock` (`uv.lock` records the
   project version, so every `--locked` gate fails without it), and land both
   files on `main` through a pull request. `main`'s ruleset requires a PR, so
   a direct push is rejected. The tag check in `check-hooks` requires the tag
   to equal `v` plus that version, compared whole.
2. After the PR merges, pull `main`, then tag and push the tag as `kgrizz-git`:
   `git tag v<version> && git push origin v<version>`.
3. `release.yml` runs: the three check jobs re-run `ci.yml`'s gates, then
   `build-macos` freezes the unsigned `.app` and `build-linux` builds and
   smoke-tests the AppImage and tarball. `sign-macos` waits for the
   maintainer's approval on the `release` environment
   (one-account control, accepted 2026-11-17 — see the environment section).
   Approve only after confirming the run's commit is on `main`; that approval
   is what keeps the secrets from an unreviewed commit. It then signs, notarizes and staples the `.app` and the DMG. `publish` verifies the tag still points at
   the tagged commit, writes `SHA256SUMS`, attests the artifact and the sums,
   and creates a **draft** release. The signature gate runs `stapler validate`
   on the DMG and on the unmounted, stapled `.app`. The app inside the mounted
   DMG gets `codesign --verify --deep --strict` and `spctl --assess` only,
   because `hdiutil` can drop the staple ticket's xattr. `check-audit` audits
   the runtime dependencies plus the `build` group (PyInstaller, Pillow).
   A re-run after a failed `publish` reuses the existing draft and replaces
   its assets (`gh release upload --clobber`). It fails rather than touch a
   release that is already published. If the draft is published while the job
   runs, immutable releases make the asset upload fail, and the job checks
   again before editing the notes. Immutable releases lock assets and the tag,
   not the title or notes, so a publish in the last moment before the edit
   could still overwrite those two. Worse, `--clobber` deletes each old asset
   before uploading its replacement. A publish in that gap leaves a published
   release missing that asset, and immutability then blocks re-adding it.
4. Wait until every `release.yml` run for the tag has finished. While a draft
   is being checked or published, no run may be in progress.
5. Check the draft's final assets: the DMG, the Linux AppImage and `.tar.gz`,
   `build-info.json`, `build-info-linux.json` and `SHA256SUMS` are all
   present and the checksums match.
6. Do the manual acceptance below on a machine with no user-installed Python
   on `PATH` (no uv-managed, pyenv or Homebrew interpreter; Apple's
   `/usr/bin/python3` may be present).
7. If step 5 or 6 fails, abort acceptance and leave the draft unpublished.
   Then decide which kind of failure it is.
   - A transient failure, such as a missing or corrupt asset from an
     interrupted run, or a notarization or network error: re-run the
     workflow, wait for it to finish (step 4), and repeat steps 5 and 6 from
     the start.
   - A deterministic defect in the app: a re-run rebuilds the same tagged
     commit, so it cannot fix the defect. Delete the draft, fix the defect on
     `main` through a PR, and cut a new version from step 1. Re-tagging the
     same version needs the [Rollback](#rollback) procedure; prefer a new
     version.
8. Publish the draft. The workflow never publishes a final release.

`v0.1.0` stays source-only; the first run is the next version bump.

## Rollback

A published release is immutable: its assets cannot be replaced, so a bad
published release is fixed by a new version, not by editing it. A draft can be
deleted from the Releases page. A tag needs the
immutability ruleset temporarily opened, and the ruleset can only be edited by
`kgforais1`:

1. `kgforais1` adds itself to `v-tag-immutability`'s bypass actors.
2. `kgforais1` deletes the tag: `git push origin :refs/tags/v<version>`.
3. `kgforais1` removes that bypass entry, in the same session.
4. `kgrizz-git` pushes the replacement tag.

Leaving the bypass entry in place drops immutability for every `v*` tag, so
steps 1–3 are one operation. Record the date and the reason in the release
notes or the commit that re-tags.

## Acceptance checklist

Blocking gate for publish: the drafted artifact for every platform the release
contains is accepted on a machine with no **user-installed** Python on `PATH`
(no uv-managed, pyenv or Homebrew interpreter) — launch it, create an archive
with a generated password, open it. The Apple-provided `/usr/bin/python3` may
be present on macOS; it ships with the OS and is not a user install. Linux
uses the M3 environment below; Windows is deferred.

- **M1 (local macOS, done 2026-11-15, macOS 26 / darwin 25.6.0):** the unsigned
  app and DMG from `dist/0.1.0/` were opened; a synthetic quarantine xattr
  triggered the Gatekeeper refusal, the app was launched with Privacy & Security
  → Open Anyway, and it created an archive that opened. M1 has no CI.
- **M2 (macOS, from the draft release, in a clean Standard second account or
  VM with no user-installed Python on `PATH`; Apple's `/usr/bin/python3` may
  be present):** download the DMG fresh (the browser sets quarantine), open
  it, drag to Applications, launch, create an archive with a generated
  password, open it in Finder and 7-Zip. Record the date, macOS version and
  which `python3` was visible here.
  - **v0.2.0 deviation (2026-11-19, macOS 26 / darwin 25.6.0, DMG SHA-256
    `9da7a00b7e64e8692c7204312800590f464e4d3a5825682cc572699c8f733b8e`):**
    the signed/notarized draft was installed in the Standard `test` account
    and passed the Finder launch and archive workflow, but the login shell
    saw Homebrew `/opt/homebrew/bin/python3` (3.14.7) through
    `/etc/paths.d/homebrew`; unadorned `python` was absent. The
    Finder-launched app's PATH was not separately measured, so the literal
    no-user-installed-Python condition was not established. Static
    inspection found bundled Python/Tcl/Tk, only system or bundle-relative
    direct Mach-O dependencies, and no first-party external interpreter.
    Accepted by the maintainer as a deviation, not an unqualified M2 pass;
    the strict check remains open for a clean VM.
  - **v0.3.0 deviation (approved 2026-11-25; static checks 2026-11-24 on
    macOS 27.2.1 / build 26B131; DMG SHA-256
    `5010da06884ab13206dc4360a044913a4c7154421ab4551ba8819d68d3c326aa`):**
    no new manual macOS launch was performed. The maintainer accepted the
    v0.3.0 release without a new manual macOS acceptance because it rebuilds,
    signs and notarizes the same app; the draft DMG passed static `hdiutil`,
    `codesign`, `spctl` and `stapler` checks. The static-check shell's visible
    `python3` was the pyenv shim 3.12.10, Homebrew
    `/opt/homebrew/bin/python3` and `/usr/bin/python3`; the Finder-launched
    app's PATH was not measured because it was not launched. The literal
    no-user-installed-Python condition remains open; the strict M2 check
    stays open for a clean VM.
- **M3 (Linux; Windows deferred, from the draft release):** run the Linux
  artifacts in a clean Linux VM with no system Python; create an archive with
  a generated password and open it in 7-Zip or `bsdtar`. Record the date and
  OS here. The Windows zip is not part of a release until the core filesystem
  port lands.
  - **v0.3.0 Linux deviation (2026-11-22; 7z t verified 2026-11-23, Ubuntu
    22.04.5 LTS amd64 container on Docker/Colima, no system Python):** the
    maintainer accepts the clean-container check as the Linux acceptance for
    v0.3.0 instead of a literal VM. The rehearsal tarball from run
    45077481075 added `/work/input`, generated a password, and wrote a
    one-part AES-256 archive (418 bytes); `7z t` reported `Everything is Ok`
    with the generated password (2 files, 48 bytes), and `7z l` listed
    `input/hello.txt` and `input/notes.txt`. The AppImage launched via
    `qemu-user-static`. This exception applies to v0.3.0 only; later releases
    require a clean VM unless a new deviation is recorded. The literal
    clean-VM check remains open.
  - **v0.3.0 draft repeat (2026-11-24, same container):** the draft tarball
    and AppImage both added `/work/input`, generated a password, and wrote a
    one-part AES-256 archive (418 bytes); `7z t` reported `Everything is Ok`
    (2 files, 48 bytes), `7z l` listed `input/hello.txt` and
    `input/notes.txt`, and both entries were `AES-256 Deflate`. The AppImage
    needed `qemu-x86_64-static -cpu max` on the arm64 Colima host; qemu 6.2's
    default CPU model segfaulted on the newer runtime. The draft was published
    on 2026-11-24. The strict clean-VM check remains open.

## Runner images

| Job | Image | Since |
|---|---|---|
| `build-macos`, `sign-macos` | `macos-15` | 2026-11-15 |
| `build-linux` | `ubuntu-24.04`; container `ubuntu@sha256:f64b2ffc2f10ab8f8505aa56b2664bd846cbb9df87c7e2532e30f7667021c0e6` (22.04) | 2026-11-21 |
| `publish` | `ubuntu-24.04` (pinned; not `-latest`) | 2026-11-16 |
| `check-hooks` | `ubuntu-latest` (same as `ci.yml`; the `uv sync` step is hardened, see below) | 2026-11-16 |
| `check-audit` | `ubuntu-latest` (identical to `ci.yml`; nothing hardened) | 2026-11-16 |
| `check-test` | matrix `ubuntu-latest` and `macos-latest`, Python 3.11/3.13 (same runners as `ci.yml`; the `uv` sync/pytest steps are hardened, see below) | 2026-11-16 |

Only the build/sign/publish images are versioned labels per Decision 6 (a tag
must not change under the project without a commit). The check jobs share
`ci.yml`'s runners, runner labels and gates, but their `uv sync` and pytest
steps are hardened for SonarCloud (`--no-build --no-install-project`,
`PYTHONPATH=src`) — a deliberate, documented divergence from `ci.yml`. The
`check-pins` and `basedpyright` hooks still re-run their own `uv run`,
basedpyright with `--group build`, so they can build and install the project
through `uv_build`. Bumping any of these labels
is its own commit and is recorded here with the previous value.

## Tool pins

The uv version lives once, in `.github/uv.toml`
(`required-version = "==0.13.9"`). Every `astral-sh/setup-uv` step passes
`version-file: .github/uv.toml`; `check-pins` rejects a step that omits it,
names another file, or pins a range. Bump the one file in its own commit and
record the previous value here. `BUILD_PYTHON` (3.13.17) is separate:
`release.yml` and `packaging/build.py` must agree, and `check-hooks` enforces
that pair.

## Dispatch rehearsal

`workflow_dispatch` runs `check-hooks`, `check-test`, `check-audit` and, only if
those pass, `build-macos` and `build-linux`. It skips `sign-macos` and
`publish`: no `release` environment and no secrets. The tag-equals-version
check stays tag-push only. `workflow_dispatch` is accepted only on
`refs/heads/main`. `check-hooks` fails a dispatch on any other ref, and the
build jobs are also guarded on the ref, so a branch cannot be rehearsed this
way. A Linux build or smoke failure stops the rehearsal. Rehearse after merging to `main`. Pushing a tag is what creates the draft
release, so a rehearsal tag would not do.

The first green rehearsal ran 2026-11-19 (run 44590496069) on `main` at
`8f9a814`: `check-hooks`, `check-test`, `check-audit` and `build-macos`
passed, and `sign-macos`/`publish` were skipped as designed. The macOS
`build.py` preflight ran on the headless runner.
