# Plan: SHA-pin the pre-commit hook revs, pin uv, and guard both

Date: 2026-10-15
Status: draft
Linked: `TODO.md` "SHA-pin the CI tooling and guard it"

Reviewed by Gemini 3.8 Flash High, then by Claude Sonnet 5.5 High. Findings from
both rounds are folded in; the corrections they forced are called out inline.

## Goal

Several surfaces in CI still resolve a version at run time instead of pinning an
immutable identifier. All are the same threat class as the `uses:` SHA pins that
PR #6 established. Finish the job, add a guard so it cannot silently regress,
and record what remains open rather than implying full coverage.

## Background

After PR #6 every `uses:` is a SHA that resolves to a release tag, which is what
zizmor's `known-vulnerable-actions` audit needs:

| Action | SHA | Tags at that SHA |
| --- | --- | --- |
| `actions/checkout` | `3d3c42e5aac5ba805825da76410c181273ba90b1` | `v7.0.1`, `v7` |
| `astral-sh/setup-uv` | `c18668ad3cf93ea998bef934396af7bb5c839dc7` | `v10.2.0` |

What is still mutable:

1. `.pre-commit-config.yaml` pins four hook repos by mutable tag.
2. `setup-uv` installs whatever uv the `version` input resolves to, which
   defaults to the pyproject version or `latest`.

`uv.lock` is fine for the project's own dependencies: 210 `sha256` hashes.

## Task 1: SHA-pin the four pre-commit hook revs

File: `.pre-commit-config.yaml`. Two of the four hooks are already behind, so
this re-pins all four and bumps the two that have moved. Every SHA below was
resolved with `git ls-remote` and then verified to install and run against the
whole repo.

| Repo | Current rev | New tag | New commit SHA | Tag type |
| --- | --- | --- | --- | --- |
| `gitleaks/gitleaks` | `v8.30.0` | `v8.30.1` | `83d9cd684c87d95d656c1458ef04895a7f1cbd8e` | lightweight |
| `pre-commit/pre-commit-hooks` | `v6.0.0` | `v6.0.0` (no bump) | `3e8a8703264a2f4a69428a0aa4dcb512790b2c8c` | lightweight |
| `astral-sh/ruff-pre-commit` | `v0.16.10` | `v0.17.1` | `38bfb07c0c64c304f47eb52090f8288150c77730` | lightweight |
| `DavidAnson/markdownlint-cli2` | `v0.23.3` | `v0.23.3` (no bump) | `916ad0aaa108c64d294101002066f530ea170b10` | lightweight |

Latest tags came from
`git ls-remote --tags --refs <repo> | sed 's#.*refs/tags/##' | sort -V | tail -1`.
`pre-commit-hooks` and `markdownlint-cli2` are already newest, so only their
`rev` format changes.

The resulting diff to `.pre-commit-config.yaml` is four lines:

```yaml
  - repo: https://github.com/gitleaks/gitleaks
    rev: 83d9cd684c87d95d656c1458ef04895a7f1cbd8e  # v8.30.1
    hooks:
      - id: gitleaks

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: 3e8a8703264a2f4a69428a0aa4dcb512790b2c8c  # v6.0.0
    hooks:
      # unchanged

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: 38bfb07c0c64c304f47eb52090f8288150c77730  # v0.17.1
    hooks:
      # unchanged

  - repo: https://github.com/DavidAnson/markdownlint-cli2
    rev: 916ad0aaa108c64d294101002066f530ea170b10  # v0.23.3
    hooks:
      # unchanged
```

### Two commits, not one

Keep this in one PR but split it across two commits:

1. **Pin only, versions unchanged.** Re-point the four `rev:` values at the
   commit SHAs of the tags already in the file. This diff is mechanically
   checkable: same version, now immutable. gitleaks v8.30.0 becomes
   `6eaad039…`, not `2ca41cc…`.
2. **Then bump.** gitleaks to v8.30.1, ruff-pre-commit to v0.17.1.

Reverting the bump should not revert the pin. A single squashed commit means
`git revert` of the ruff bump also un-hardens gitleaks, and a reviewer cannot
confirm "same version, now immutable" when the version changes in the same diff.

Re-pinning a stale SHA without bumping is a false economy either way: it locks
in old code behind fresh process. The bumps are small and verified:

- `gitleaks` v8.30.0 to v8.30.1: four commits, eight files, +79/-11. Go 1.24
  build switch, goreleaser and report-template tidy-up, plus small
  `detect/codec` encoding changes. It touches the secret-scanning gate, so it
  deserves its own commit.
- `ruff-pre-commit` v0.16.10 to v0.17.1 is a **minor** release and carries the
  real risk, since a new ruff can add or change rules and turn the lint gate
  red. Tested against this repo: `ruff-check` and `ruff-format` both pass
  unchanged on all files. If a future bump trips the gate, fix or configure the
  new findings rather than reverting the pin.

### gitleaks v8.30.1 is not on master, and that matters

Verified against a bare clone of `gitleaks/gitleaks`:

```
v8.30.0 -> 6eaad039...  on master
v8.30.1 -> 83d9cd68...  NOT on master   (only ref containing it: refs/tags/v8.30.1)
git describe --tags master -> v8.30.0-27-gb58d3f1
```

v8.30.1 is a release cut from a side branch that never reached master. Two
consequences:

- The commit is still safe to pin. `refs/tags/v8.30.1` keeps it reachable, so
  upstream will not garbage-collect it, and `pre-commit` installed and ran it
  successfully here.
- **`pre-commit autoupdate` will not select it, and will move gitleaks back to
  v8.30.0.** So the bump is a silent downgrade. This is a second, stronger
  reason the header rewrite below is mandatory, and it is exactly what the
  Task 3 guard catches.

### Resolving a tag to a commit SHA

`gitleaks` v8.30.0, the tag currently in the file, is an **annotated** tag, so
`git ls-remote` reports two refs:

```
2ca41cc1372d1e939a6a879f18cdc19fc1cac1ce  refs/tags/v8.30.0
6eaad039603a4de39fddd1cf5f727391efe9974e  refs/tags/v8.30.0^{}
```

`2ca41cc…` is the *tag object*, not the commit. The `^{}` line is the commit, and
that is what belongs in `rev`. The other three are lightweight tags, where the two
lines collapse to one and the tag ref is already the commit. All four *new* tags
happen to be lightweight, so the trap is easy to forget next time.

Use the peeled form, and guard it, because a mistyped tag yields an empty string
and still exits 0:

```sh
sha=$(git ls-remote https://github.com/<repo> \
        'refs/tags/<tag>' 'refs/tags/<tag>^{}' | tail -1 | cut -f1)
test -n "$sha" || { echo "no such tag: <tag>" >&2; exit 1; }
case "$sha" in
  *[!0-9a-f]*) echo "not a SHA: $sha" >&2; exit 1 ;;
esac
```

Do not filter on `rg '\^\{\}$'`: that matches nothing for a lightweight tag,
which is three of the four here. `tail -1` handles both.

For reference, both action pins in the workflows are lightweight tags, so
`3d3c42e…` and `c18668a…` are already commit SHAs.

### This task has a documentation trap

The header of `.pre-commit-config.yaml` currently says:

```
# Bump pinned revisions:   pre-commit autoupdate
```

`pre-commit autoupdate` rewrites `rev` back to a tag. Verified empirically
against a throwaway copy of the config carrying the plan's exact pin:

```
[https://github.com/astral-sh/ruff-pre-commit] updating f12be1ebaa5351c1fc76472de98db2c3446c8253 -> v0.17.1
```

It stripped the `# v0.16.10` comment and replaced the SHA with the tag.
`autoupdate --freeze` is **not** a safe substitute: it chose v8.30.0 over the
newer v8.30.1 for gitleaks, and it wrote the annotated tag-object SHA
`2ca41cc…` for v8.30.0 rather than the commit.

The header must be rewritten in the **first** commit of this task, the one
that introduces the SHAs, so the file is never in a state where the pins exist
and the instruction to replace them with tags still stands:

```
# Bump pinned revisions:   see "Bumping hook revs" below
```

The procedure to document: for each repo, find the newest tag with the
`sort -V` form above, resolve it to a commit SHA with the guarded peeled form,
then update `rev` and its tag comment together. The tag comment is the only
human-readable record of which release a SHA is, so the two must never drift
apart.

### Risk

- `pre-commit autoupdate` stops being the bump command. That is the point, but
  it is a real workflow change for whoever maintains this repo.
- No automated bump path. Dependabot has no ecosystem for pre-commit revs and
  pre-commit.ci is not configured, so hook bumps stay manual. Acceptable for
  four repos that move a few times a year; revisit if that stops being true.
- A wrong SHA fails loudly at `pre-commit run` time, not silently. Good.

## Task 2: pin the uv version in setup-uv

Five steps carry `astral-sh/setup-uv`, and all five need the change:

| File | Line | Job |
| --- | --- | --- |
| `.github/workflows/ci.yml` | 30 | `checks` |
| `.github/workflows/ci.yml` | 47 | `test` |
| `.github/workflows/ci.yml` | 67 | `audit` |
| `.github/workflows/dependency-audit.yml` | 51 | `audit` |
| `.github/workflows/dependency-audit.yml` | 64 | `vulnerable-actions` |

Add to each:

```yaml
      - uses: astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7  # v10.2.0
        with:
          version: "0.12.24"
```

`version` is unset today, so uv has been whatever the input resolved to by
default. From the pinned action's own `action.yml` at v10.2.0:

```yaml
  version:
    description: "The version of uv to install, e.g., `0.5.0`, `latest`, or `latest-known`. Defaults to the version in pyproject.toml or `latest`."
    default: ""
```

Two things follow. This repo has no `[tool.uv]` section in `pyproject.toml`, so
the documented default resolves to `latest`: every CI run has used whatever uv
was newest that day. And because the action reads pyproject.toml first, adding
`[tool.uv] required-version` later would silently start governing this too.

### Why 0.12.24 and not 0.12.10

Current tags are `0.12.24` (newest 0.12.x) and `0.13.1` (newest overall). Pin
the newest patch of the 0.12 line rather than whatever version happened to be on
the machine when PR #6 was written, for the same reason the hook pins move:
hardening shipped on stale code is still stale code.

`0.12.24` rather than `0.13.1` is a judgement call, not a hard constraint. The
`<0.13.0` cap in `pyproject.toml:28` applies to `uv_build`, the build backend,
which is a separate package from the `uv` CLI, so it does not forbid a 0.13 CLI.
What it does indicate is that the repo is mid-migration: open PR #4 widens
`uv_build` to `<0.14.0`. Pinning the CLI to 0.12.x keeps it consistent with the
backend generation actually in use and keeps `--no-build` semantics on a line
stable since 0.12.0. Revisit when PR #4 lands.

Accepted values are an exact version, `latest`, or `latest-known`. Inequality
operators such as `">=0.12.10"` are not supported by this input, so a "floor"
cannot be expressed that way.

An exact pin has a second benefit: setup-uv verifies its own download checksum
for a pinned version, which the `latest` path cannot.

Because this pin changes which binary runs every `uv`, `uvx` and `uv sync`
command in CI, the whole Verification block must be re-run **under 0.12.24**.
PR #6 validated 0.12.10 only.

### Sequencing: open PR #3 collides

PR #3 (`Bump astral-sh/setup-uv from 10.2.0 to 10.3.0`) edits the same `uses:`
lines. Land PR #3 first, then apply this task on top. After PR #3 lands,
re-check that the new SHA resolves to a release tag:

```sh
git ls-remote https://github.com/astral-sh/setup-uv 'refs/tags/<new-tag>' \
  'refs/tags/<new-tag>^{}'
```

No output means no tag points at that commit, and zizmor's
`known-vulnerable-actions` audit cannot check it. The job does not fail in that
case; it silently checks less.

## Task 3: a policy hook so the pinning cannot silently regress

Tasks 1 and 2 both rest on a convention that nothing enforces, so the guard has
to cover both. `pre-commit validate-config` only checks schema, so it accepts
`rev: v8.30.0` happily; and nothing at all checks that a `setup-uv` step still
carries an exact `version:`. One `autoupdate` run, one dropped `version:` line,
and CI stays green. That is precisely the failure mode this plan exists to
close, so the plan should close it for itself.

Add `hooks/scripts/check_pins.py`, following the existing local-hook pattern
alongside `check_file_size.py`, `check_personal_data.py` and the rest. Two
rules:

1. **Hook revs.** In `.pre-commit-config.yaml`, every `repo:` entry must have a
   `rev` that is a full 40-character lowercase hex SHA, **except** the two
   reserved values `local` and `meta`, which take no `rev`.
2. **uv versions.** In every workflow, each `astral-sh/setup-uv` step must set
   `with.version` to an exact version. Reject empty, `latest`, and
   `latest-known`, since all three resolve at run time.

Rule 1 is stated as "everything except `local` and `meta`" rather than "every URL" on purpose: pre-commit also accepts SCP-style remotes such as
`git@github.com:owner/repo.git`, # personal-data:allow: SCP-style git remote cited as an example, not an email address
which a scheme check would miss, leaving a tag pin in place that no rule objects to.

Register it in the `repo: local` block, widening `files:` to both surfaces:

```yaml
      - id: check-pins
        name: "policy: immutable version pins"
        entry: python3 hooks/scripts/check_pins.py
        language: system
        files: '^(\.pre-commit-config\.yaml|\.github/workflows/[^/]+\.ya?ml)$'
```

### Implementation constraint: stdlib only, fail closed

`language: system` runs the interpreter found on the runner, so an undeclared
import is a portability bug. **Every existing policy hook is stdlib-only** —
none of them imports PyYAML — and this one must be too, even though PyYAML
happens to be importable in some local environments. That rules out a YAML
library and puts the burden on a line-oriented parser.

The parser must therefore **fail closed**: if it meets a shape it does not
recognise, such as a YAML anchor or alias, a CRLF line ending, a nested or
quoted `rev`, or anything malformed, it reports a failure rather than skipping
the entry. A guard that quietly passes what it cannot read is worse than no
guard, because it reads as protection that is not there.

Rule 2 is the harder of the two, because a GitHub workflow nests mappings and
lists inside a step and may contain `${{ }}` expressions and block scalars.
The check should be narrow and structural: locate each `uses:` line whose action
is `astral-sh/setup-uv`, walk forward within that step's block, and require a
`version:` key holding an exact version. If the block boundary is ambiguous,
fail closed. If this proves unreliable in practice, the fallback is to declare
PyYAML in the `dev` dependency group and change the entry to `uv run python`,
which matches the existing `uv run basedpyright` hook — but that adds a
dependency, so try the stdlib route first.

Neither rule can confirm offline that a 40-hex string is a *commit* rather than
a tag object, which is the gitleaks v8.30.0 trap. That fails loudly anyway,
because `pre-commit` cannot check out a tag object, so the mode of failure is
safe. A CI-side `git ls-remote` reachability check, if wanted later, belongs in
the audit workflow rather than in this hook.

## Checklist

Tick a box only when the task is done and verified by a command or an explicit
acceptance, per the lifecycle in `dev-docs/README.md`.

### Commit 1: pin, and close the loopholes

- [ ] Re-point the four `rev:` values at the commit SHAs of the tags already in
      the file, versions unchanged (gitleaks v8.30.0 becomes `6eaad03…`).
- [ ] Rewrite the `.pre-commit-config.yaml` header bump instruction in this same
      commit, since the trap it describes is created here.
- [ ] Add `hooks/scripts/check_pins.py` and register it, covering both rule 1
      and rule 2.
- [ ] Verify the guard against the fixture matrix in Verification, including
      that it fails closed.
- [ ] Confirm the four pinned hooks install and pass from their SHAs.

### Commit 2: bump

- [ ] Bump gitleaks to v8.30.1 (`83d9cd6…`) and ruff-pre-commit to v0.17.1
      (`38bfb07c…`).
- [ ] Confirm each new SHA matches its new tag comment.
- [ ] Re-run the full pre-commit gate and confirm ruff 0.17 did not change any
      finding.

### Task 2: pin uv

- [ ] Land open PR #3 first, then re-verify the new action SHA has a tag.
- [ ] Add `with: version: "0.12.24"` to all five `setup-uv` steps.
- [ ] Re-run the whole Verification block **under uv 0.12.24**, not the local uv.

### Close out

- [ ] Log in `CHANGELOG.dev.md` and delete the `TODO.md` item.
- [ ] Set `Status:` and move to `plans/archive/`.

## Verification

Already run against this tree while drafting this plan, using throwaway configs
outside the repo, each hook installed from its raw SHA rev and run over all
files:

```sh
# SHA revs work as `rev:` values at all
uvx --no-build pre-commit==4.7.0 run --config <sha-rev config> --all-files
# -> gitleaks Passed, ruff check Passed

# the corrected gitleaks commit SHA (not the tag object) installs and passes
#   rev: 6eaad039603a4de39fddd1cf5f727391efe9974e  # v8.30.0
# -> Detect hardcoded secrets...Passed

# both proposed bumps install and pass on this repo
#   gitleaks 83d9cd68... (v8.30.1) and ruff-pre-commit 38bfb07c... (v0.17.1)
# -> Detect hardcoded secrets...Passed
# -> ruff check...Passed
# -> ruff format...Passed
```

After applying the tasks, under uv 0.12.24:

```sh
uv --version                                              # expect 0.12.24
pre-commit validate-config .pre-commit-config.yaml
uvx --no-build pre-commit==4.7.0 run --all-files          # all hooks pass
uv export --locked --no-dev --no-hashes --format requirements-txt -o "$RUNNER_TEMP/req.txt"
uvx --no-build pip-audit==2.10.1 -r "$RUNNER_TEMP/req.txt"
uvx --no-build --python 3.12 zizmor==1.31.0 --format=json . # gate exits 0
uv run pytest -q
actionlint .github/workflows/*.yml                          # workflow shape
```

`actionlint` earns its place: hand-editing a workflow to add a `with:` block is
exactly the change most likely to break indentation or step structure, and
PyYAML would happily parse a structurally wrong file.

### Structural assertions

These catch the specific mistakes the happy path would miss:

- Every one of the five `astral-sh/setup-uv` steps carries
  `version: "0.12.24"`, and the count of `version:` keys under those steps
  equals the count of `setup-uv` steps. Assert with a count, not an eyeball.
- Each pinned SHA matches the tag in its own trailing comment. A reachable old
  SHA with a freshly bumped comment installs and passes every hook, while
  silently violating the tag-comment convention in this plan. Compare them
  mechanically:

  ```sh
  for repo in gitleaks/gitleaks pre-commit/pre-commit-hooks \
              astral-sh/ruff-pre-commit DavidAnson/markdownlint-cli2; do
    tag=$(grep -A1 "repo: https://github.com/$repo" .pre-commit-config.yaml \
          | rg -o '#\s*v\S+' | tr -d '# ')
    sha=$(grep -A1 "repo: https://github.com/$repo" .pre-commit-config.yaml \
          | rg -o '^[0-9a-f]{40}')
    actual=$(git ls-remote "https://github.com/$repo" \
              "refs/tags/$tag" "refs/tags/$tag^{}" | tail -1 | cut -f1)
    [ "$actual" = "$sha" ] || echo "MISMATCH $repo: $tag is $actual, pinned $sha"
  done
  ```

### Guard fixture matrix

`check_pins.py` is verified by making it fail, across a fixture matrix rather
than the single tag-`rev` case. Each case states the expected outcome:

| Fixture | Expected |
| --- | --- |
| valid 40-hex lowercase `rev` | pass |
| tag `rev` (`v8.30.0`) | fail, rule 1 |
| SCP remote with a tag `rev` | fail, rule 1 |
| uppercase hex `rev` | fail, rule 1 |
| short or over-long hex | fail, rule 1 |
| non-string `rev` (unquoted number, nested map) | fail, rule 1 |
| `local` or `meta` repo, no `rev` | pass |
| YAML anchor/alias in place of a `rev` | fail closed |
| CRLF line endings | fail closed |
| malformed YAML | fail closed |
| repo entry with `rev` but no `hooks` | fail closed |
| `setup-uv` step with no `version:` | fail, rule 2 |
| `setup-uv` step with `version: latest` | fail, rule 2 |
| `setup-uv` step with `version: latest-known` | fail, rule 2 |
| `setup-uv` step with exact `version:` | pass |
| unrelated workflow file with no `setup-uv` | pass |

Pre-commit already rejects an empty or missing `rev`, a `rev` on `local`/`meta`,
and an entry with no `hooks`, so those cases are belt-and-braces; the point of
the matrix is that our guard never passes something it could not read.

### What local verification cannot confirm

The zizmor gate's `known-vulnerable-actions` audit is online-only and needs
`GH_TOKEN`. Without it, zizmor silently skips the audit that matters most and
still exits 0, so a local green run proves only that the gate's plumbing works.
The advisory check itself has to be confirmed by a real CI run.

## Known remaining holes

Not fixed by any task here. Recorded so they are not mistaken for covered.

- `pyproject.toml:28` requires `uv_build>=0.12.10,<0.13.0`, and `uv_build` is
  **not in `uv.lock`** (confirmed by grep). Every `uv sync --locked` builds the
  project with a backend resolved from that range at run time, unhashed and
  unreviewed. Narrowing the range or locking the backend would close it.
- The `uvx` tools in `ci.yml` and `dependency-audit.yml` have exact version
  pins but no hashes. PyPI immutability makes a same-version swap impossible,
  but nothing is hash-verified either. This is what the `[dependency-groups]`
  item in `TODO.md` would close.
- SHA-pinning a pre-commit hook repo pins the hook definition, not the
  dependencies of its environment. `ruff-check` (`language: python`) and
  `markdownlint-cli2` (`language: node`) both install transitive packages at
  run time, so their trees stay unpinned. Inherent to pre-commit, not fixable
  by pinning `rev`.
- `apt-get install 7zip` and `brew install sevenzip` in `ci.yml` are unpinned.
  Test jobs only, so low risk.
- Python selectors float to the newest patch of their minor. `ci.yml` uses
  `python-version: ${{ matrix.python }}` with `3.11` and `3.13`, and
  `dependency-audit.yml:76` passes `--python 3.12` to `uvx`, so each resolves to
  whatever patch is current that day. Pinning patch-exact would fix it at the
  cost of never getting interpreter security patches automatically. Ordinary
  practice, recorded so it is not mistaken for a pin.
- `runs-on: ubuntu-latest` and `macos-latest` float, so the base image changes
  under the CI run. A dated image label would fix it at the cost of routine
  security patching.

## Not in this plan

Moving `pip-audit`, `pre-commit` and `zizmor` into a `[dependency-groups]` entry
in `pyproject.toml` for `uv.lock` hash verification. Already recorded in
`TODO.md`; it is a bigger change with its own trade-offs and should not be
bundled with this one.

## Rollback

Tasks 1 and 2 are single-file or single-line reverts with no state migration. If
a pinned SHA turns out to be wrong, revert that one `rev` and re-run
`pre-commit run --all-files`. Because Task 1 is split into pin and bump commits,
reverting a bump does not un-pin anything.

Task 3 is additive: deleting the hook registration and the script restores the
prior state.
