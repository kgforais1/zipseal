# Releasing zipseal-gui

Last reviewed: 2026-11-16

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
| Required `release` reviewer; edits the rulesets | `kgforais1` |

The repository owner is also the tag-pushing account's operator: both accounts
belong to the same person. The plan's split is therefore a two-account
*convention* — the tag-pushing account cannot self-approve under
`prevent_self_review` when self-review prevention is on — not a second-person
control. As of 2026-11-16 the owner changed the required reviewer list and
turned `prevent_self_review` off in the UI, so that convention is currently
suspended; `can_admins_bypass` is likewise on. All three settings are recorded
here, not assumed. The `v-tag-immutability` ruleset (empty bypass list) is the
remaining structural control: it blocks an accidental or malicious tag move
regardless of account.

## Repository protections

### `release` environment

**Live state as of 2026-11-16** (created 2026-11-16T04:28:29Z):

- Deployment policies: custom `v*` policy of type `branch` (created 2026-11-16)
  followed by a custom `v*` policy of type `tag` (added the same day; a
  branch-only policy does not apply to tags).
- Required reviewers: **`kgforais1` and `kgrizz-git`** — the repository owner
  changed the required reviewer list in the UI, with both accounts being the
  same person's. The intended split (owner reviews; tag-pushing account cannot
  self-approve) therefore does not currently hold as the plan specifies; it
  is equivalent to a single person holding both roles.
- Prevent self-review: **off** (same UI change; see above).
- Allow administrators to bypass: **on**. The environments REST API has no
  body parameter for this (`wait_timer`, `prevent_self_review`, `reviewers`,
  `deployment_branch_policy` only), so it cannot be verified or set from a
  script. To turn it off: Settings → Environments → `release` → uncheck
  "Allow administrators to bypass".
- Wait timer: 0.
- Secrets: none stored yet. Add them no earlier than when the M2 acceptance is
  actually due; do not store placeholder or throwaway values.

`environment` is job-level, so only `sign-macos` requests it. `build-macos` runs
on both triggers with no environment and no secrets; a `workflow_dispatch`
cannot reach the secrets because `sign-macos` is event-guarded.

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
| `KEYCHAIN_PASSWORD` | ephemeral CI keychain password |

Origin: the certificate and API key come from the Apple Developer account that
already exists for this project. Rotation: re-export the `.p12` and `.p8`,
base64 them, and replace the environment secrets; no repository change is
needed. Never put a secret value in this file, a workflow, a log or a test.

**Known exception, recorded deliberately.** `security` has no stdin mechanism
for the keychain password or the `.p12` import password, and the plan prescribes
those exact commands, so `KEYCHAIN_PASSWORD` and `APPLE_CERT_PASSWORD` travel in
argv inside the (job-scoped, ephemeral-runner-scoped) `sign-macos` steps. This
is a deliberate tension with AGENTS.md's "never put a password in argv": the
values are not printed to the log, the runner is destroyed afterwards, and the
alternative (an expect-like wrapper or a passwordless keychain) would weaken
hardening rather than help. If a stdin path appears in a future `security`,
switch to it.

## Tag to release

1. Bump `version` in `pyproject.toml`, commit to `main`, and push. The tag check
   in `check-hooks` requires the tag to equal `v` plus that version, compared
   whole.
2. Tag and push the tag as `kgrizz-git`:
   `git tag v<version> && git push origin v<version>`.
3. `release.yml` runs: the three check jobs re-run `ci.yml`'s gates, then
   `build-macos` freezes the unsigned `.app`, smoke-tests it, and uploads it.
   `sign-macos` waits for a `kgforais1` approval, then signs, notarizes and
   staples the `.app` and the DMG. `publish` verifies the tag still points at
   the tagged commit, writes `SHA256SUMS`, attests the artifact and the sums,
   and creates a **draft** release.
4. Do the manual acceptance below on a machine with no Python on `PATH`.
5. Publish the draft. The workflow never publishes a final release.

`v0.1.0` stays source-only; the first run is the next version bump.

## Rollback

A published draft can be deleted from the Releases page. A tag needs the
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
contains is accepted on a machine with no Python on `PATH` — launch it, create
an archive with a generated password, open it.

- **M1 (local macOS, done 2026-11-15, macOS 26 / darwin 25.6.0):** the unsigned
  app and DMG from `dist/0.1.0/` were opened; a synthetic quarantine xattr
  triggered the Gatekeeper refusal, the app was launched with Privacy & Security
  → Open Anyway, and it created an archive that opened. M1 has no CI.
- **M2 (macOS, from the draft release):** download the DMG fresh (the browser
  sets quarantine), open it, drag to Applications, launch, create an archive
  with a generated password, open it in Finder and 7-Zip. Record the date and
  macOS version here.
- **M3 (Windows and Linux, from the draft release):** download and run each
  artifact on a machine with no Python on `PATH`; create an archive with a
  generated password and open it in 7-Zip or `bsdtar`. Record the date and OS
  here.

## Runner images

| Job | Image | Since |
|---|---|---|
| `build-macos`, `sign-macos` | `macos-15` | 2026-11-15 |
| `publish` | `ubuntu-24.04` (pinned; not `-latest`) | 2026-11-16 |
| `check-hooks`, `check-audit` | `ubuntu-latest` (copied step for step from `ci.yml`) | 2026-11-15 |
| `check-test` | matrix `ubuntu-latest` and `macos-latest`, Python 3.11/3.13 (copied from `ci.yml`) | 2026-11-15 |

Only the build/sign/publish images are versioned labels per Decision 6 (a tag
must not change under the project without a commit); the check jobs copy
`ci.yml`'s test runners step for step, which is what the plan's Phase 2
specifies, so their `-latest` labels move with `ci.yml`. Bumping any of these
labels is its own commit and is recorded here with the previous value.

## Dispatch rehearsal

`workflow_dispatch` runs `check-hooks`, `check-test`, `check-audit` and, only if
those pass, `build-macos`. It skips `sign-macos` and `publish`: no `release`
environment and no secrets. The tag-equals-version check stays tag-push only.
`workflow_dispatch` requires the workflow on the default branch, but a dispatch
can select another ref and runs that ref's copy, so dispatching a branch
exercises the branch, not `main`. Pushing a tag is what creates the draft
release, so a rehearsal tag would not do.
