# Plan: SHA-pin the pre-commit hook revs, pin uv, and guard all three

Date: 2026-10-15
Status: complete
Linked: `TODO.md` "SHA-pin the CI tooling and guard it" (done, item removed)

## Goal

Several surfaces in CI still resolve a version at run time instead of pinning an
immutable identifier. Finish the job, add a guard so it cannot silently
regress, and record what remains open rather than implying full coverage.

## Background

After PR #6 every `uses:` is a SHA that resolves to a release tag, which is what
zizmor's `known-vulnerable-actions` audit needs:

| Action | SHA | Tags at that SHA |
| --- | --- | --- |
| `actions/checkout` | `3d3c42e5aac5ba805825da76410c181273ba90b1` | `v7.0.1`, `v7` |
| `astral-sh/setup-uv` | `1c37ad07a6a961277cf70c0d37d6f313000f5884` | `v10.3.0` |

What is still mutable:

1. `.pre-commit-config.yaml` pins four hook repos by mutable tag.
2. `setup-uv` installs whatever uv the `version` input resolves to, which
   defaults to the pyproject version or `latest`.

`uv.lock` is fine: 210 `sha256` hashes.

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

The four `rev:` lines end up as:

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

1. **Pin only, versions unchanged.** Same version, now immutable. gitleaks
   v8.30.0 becomes `6eaad039…`, not `2ca41cc…`.
2. **Then bump.** gitleaks to v8.30.1, ruff-pre-commit to v0.17.1.

A single squashed commit means reverting the bump also un-hardens gitleaks, and
a reviewer cannot confirm "same version, now immutable" when the version changes
in the same diff. The bumps are small and verified:

- `gitleaks` v8.30.0 to v8.30.1: four commits, eight files, +79/-11. It touches
  the secret-scanning gate, so it deserves its own commit.
- `ruff-pre-commit` v0.16.10 to v0.17.1 is a **minor** release and carries the
  real risk, since a new ruff can change rules and turn the lint gate red.
  Tested: `ruff-check` and `ruff-format` both pass unchanged. If a future bump
  trips the gate, fix the findings rather than reverting the pin.

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
that is what belongs in `rev`. The other tags here are lightweight, where the
tag ref already is the commit. All four *new* tags happen to be lightweight, so
the trap is easy to forget next time.

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

Do not filter on `rg '\^\{\}$'`: that matches nothing for a lightweight tag.
`tail -1` handles both.

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
`autoupdate --freeze` is **not** a safe substitute: it picked v8.30.0 over the
newer v8.30.1, and wrote the annotated tag-object SHA `2ca41cc…` instead of the
commit.

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
  it is a real workflow change.
- No automated bump path: hook bumps stay manual. Fine for four repos that move
  a few times a year; revisit if that stops being true.
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

Add a `version:` key to each. Do not touch the `uses:` line, which Dependabot
now maintains at `1c37ad07…  # v10.3.0`:

```yaml
        with:
          version: "0.12.24"
```

At `ci.yml:47` the step already has a `with:` block holding `python-version:`.
Merge the key into that block; do not paste a second `with:`, which is a
duplicate mapping key. PyYAML silently keeps only the last block, so a botched
merge would drop `python-version:` while the guard and the count assertion both
still pass. `actionlint` catches the duplicate and is the backstop, which is
why it is in Verification rather than optional.

`version` is unset today, so uv has been whatever the input resolved to by
default. From the pinned action's own `action.yml` at v10.3.0 (identical text at v10.2.0):

```yaml
  version:
    description: "The version of uv to install, e.g., `0.5.0`, `latest`, or `latest-known`. Defaults to the version in pyproject.toml or `latest`."
    default: ""
```

Two things follow. This repo has neither `uv.toml` nor a `[tool.uv]` section in
`pyproject.toml`, so the documented default (uv.toml, then pyproject, then
`latest`) resolves to `latest`: every CI run has used whatever uv was newest
that day. And because the action would read either file first if one appeared,
adding a `required-version` to either later would silently start governing
this too.

### Why 0.12.24 and not 0.12.10

Current tags are `0.12.24` (newest 0.12.x) and `0.13.1` (newest overall). Pin
the newest patch of the 0.12 line rather than the version that happened to be
installed when PR #6 was written.

`0.12.24` rather than `0.13.1` is a judgement call, not a hard constraint. The
`<0.13.0` cap in `pyproject.toml:28` applies to `uv_build`, the build backend,
which is separate from the `uv` CLI, so it does not forbid a 0.13 CLI. The repo
is mid-migration (open PR #4 widens `uv_build` to `<0.14.0`), so pin to the
backend generation in use and revisit when PR #4 lands.

The `version` input accepts more than its description suggests. The action.yml
description mentions only exact versions, `latest` and `latest-known`, but the
README documents a `resolution-strategy` for resolving version ranges, and the
input also takes PEP 440 specifiers and partial wildcards. Every non-literal
form floats at run time. So "exact" means a full literal release version,
checked with `re.fullmatch(r"\d+\.\d+\.\d+", value)` — state the function, not
just the pattern, because under `re.match` the `$` anchor matches before a
trailing newline and `"0.12.24\n"` would pass. A leading `v` is rejected as a
harmless false positive.

An exact pin's second benefit is determinism, not exclusive checksums:
setup-uv verifies downloads on every path including `latest`. The pin fixes
which uv runs, not whether the download is checked.

Because this pin changes which binary runs every `uv`, `uvx` and `uv sync`
command in CI, the whole Verification block must be re-run **under 0.12.24**.
PR #6 validated 0.12.10 only.

### Sequencing: PR #3 has landed

PR #3 (`Bump astral-sh/setup-uv from 10.2.0 to 10.3.0`) is merged and rewrote
all five `uses:` lines to `1c37ad07…  # v10.3.0`. That tag is lightweight, so
the SHA is already the commit and zizmor can resolve it. Nothing in that diff
collides with Task 2, which now only adds `with: version:` lines and never
touches `uses:`. This section stays as a record of the ordering, not an open
dependency. For the next bump, the tag check is:

```sh
git ls-remote https://github.com/astral-sh/setup-uv 'refs/tags/<new-tag>' \
  'refs/tags/<new-tag>^{}'
```

No output means no tag points at that commit, and zizmor's
`known-vulnerable-actions` audit cannot check it. The job does not fail in that
case; it silently checks less.

## Task 3: a policy hook so the pinning cannot silently regress

Tasks 1 and 2 rest on convention: `validate-config` accepts `rev: v8.30.0`, and
nothing checks a `setup-uv` step still carries an exact `version:`. The guard
must cover all three rules, or one `autoupdate` run reverts the hardening with
CI green.

Add `hooks/scripts/check_pins.py`, following the existing local-hook pattern
alongside `check_file_size.py`, `check_personal_data.py` and the rest. Three
rules:

1. **Hook revs.** In `.pre-commit-config.yaml`, every `repo:` entry must have a
   `rev` that is a full 40-character lowercase hex SHA, **except** the two
   reserved values `local` and `meta`, which take no `rev`. Each pinned `rev`
   must also carry its release tag as a trailing comment; that comment is the
   only human-readable record of which release a SHA is, and the SHA-versus-tag
   verifier in Verification compares the two mechanically. Because
   `yaml.safe_load` discards comments, the comment check is a separate scoped
   raw-line pass over lines matching `rev:\s*[0-9a-f]{40}`: such a line must
   carry a `# tag` comment. Alias `rev` lines carry no literal hex, so the
   comment rule does not apply to them; and the raw-text pass must handle `\r`
   explicitly, since CRLF now exercises that path rather than the parser.
2. **uv versions.** In every workflow, each `astral-sh/setup-uv` step must set
   `with.version` to a full literal release version, checked with
   `re.fullmatch(r"\d+\.\d+\.\d+", value)`.
   Reject everything else the input accepts, because all of it floats at run
   time: empty, `latest`, `latest-known`, semver and PEP 440 ranges such as
   `>=0.12.10`, partial wildcards such as `0.12.x`, bare minors such as `0.12`,
   and any `${{ }}` expression, which would defer the value to something this
   check cannot see.
3. **Action refs.** In every workflow, each `uses:` that names a remote action
   (`owner/repo@…`) must pin a full 40-char lowercase hex SHA. Skip local
   paths (`./…`) and `docker://…` image refs, which are not git refs. This is
   the surface PR #6 established and the one most likely to be reverted by a
   Dependabot-style tag bump; the guard already `safe_load`s every workflow
   for rule 2, so the extra check is small and matrix-testable. A `uses:`
   reverted to a tag otherwise passes rules 1–2 silently.

Rule 1 is stated as "everything except `local` and `meta`" rather than "every URL" on purpose: pre-commit also accepts SCP-style remotes such as
`git@github.com:owner/repo.git`, # personal-data:allow: SCP-style git remote cited as an example, not an email address
which a scheme check would miss, leaving a tag pin in place that no rule objects to.

Register it in the `repo: local` block, widening `files:` to both surfaces. The
`entry:` is refined in the next section:

```yaml
      - id: check-pins
        name: "policy: immutable version pins"
        entry: python3 hooks/scripts/check_pins.py
        language: system
        files: '^(\.pre-commit-config\.yaml|\.github/workflows/[^/]+\.ya?ml)$'
```

The `files:` regex was checked against the real tree: it matches the config plus
direct `.yml` and `.yaml` files under `.github/workflows/`, and rejects
subdirectories, backup files such as `foo.yml.bak`, and unrelated paths. Those
are the extensions and locations GitHub recognises.

### Implementation constraint: use PyYAML, not a bespoke parser

Use PyYAML, not a bespoke parser: rejecting malformed input without
implementing YAML is a false promise, and workflows contain nested mappings,
`${{ }}` expressions and block scalars. Declare PyYAML in `dev` and run through
the project environment, as the existing `uv run basedpyright` hook does:

```yaml
      - id: check-pins
        name: "policy: immutable version pins"
        entry: uv run python hooks/scripts/check_pins.py
        language: system
        files: '^(\.pre-commit-config\.yaml|\.github/workflows/[^/]+\.ya?ml)$'
```

Use `yaml.safe_load`, never `yaml.load`. It parses both workflows, including
their `${{ }}` expressions and the zizmor block scalar, and finds all five
`setup-uv` steps structurally. The trade is one dev dependency for a guard that
works; `language: system` no longer implies stdlib, so the import is declared,
not assumed.

None of the rules confirms a 40-hex string is a *commit* rather than a tag object.
That fails loudly anyway, since `pre-commit` cannot check out a tag object. A
CI-side `git ls-remote` check, if wanted, belongs in the audit workflow.

## Checklist

Tick a box only when done and verified, per the lifecycle in `dev-docs/README.md`.

### Commit 1: pin, and close the loopholes

- [x] Re-point the four `rev:` values at the commit SHAs of the tags already in
      the file, versions unchanged (gitleaks v8.30.0 becomes `6eaad03…`).
- [x] Rewrite the `.pre-commit-config.yaml` header bump instruction in this same
      commit, since the trap it describes is created here.
- [x] Add `hooks/scripts/check_pins.py` and register it, covering rules 1, 2
      and 3, with each pinned `rev` carrying its tag comment.
- [x] Declare PyYAML in the `dev` dependency group and run `uv lock`, so the
      `uv run python` hook entry has its import. Without the relock,
      `uv sync --locked` fails in CI and the hook dies on `ModuleNotFoundError`.
- [x] Verify the guard against the fixture matrix in Verification, including
      that it fails closed.
- [x] Confirm the four pinned hooks install and pass from their SHAs.

### Commit 2: bump

- [x] Bump gitleaks to v8.30.1 (`83d9cd6…`) and ruff-pre-commit to v0.17.1
      (`38bfb07c…`).
- [x] Confirm each new SHA matches its new tag comment.
- [x] Re-run the full pre-commit gate and confirm ruff 0.17 did not change any
      finding.

### Task 2: pin uv

- [x] Add `with: version: "0.12.24"` to all five `setup-uv` steps, merging into
      the existing `with:` block at `ci.yml:47` rather than duplicating it.
- [x] Re-run the whole Verification block **under uv 0.12.24**, not the local uv.

### Close out

- [x] Log in `CHANGELOG.dev.md` and delete the `TODO.md` item.
- [x] Document the new hook where the repo tracks its own hooks: the hooks
      table in `dev-docs/README.md`, in the same commit. (`AGENTS.md` needs no
      change: it already points at that table.)
- [x] Set `Status:` and move to `plans/archive/`.

## Verification

Already run while drafting, using throwaway configs outside the repo, each
hook installed from its raw SHA rev and run over all files:

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
uvx --no-build --python 3.12 zizmor==1.31.0 --format=json . # raw rc is 10-14, gate asserts zero known-vulnerable-actions
uv run pytest -q
actionlint .github/workflows/*.y*ml                          # workflow shape
```

`actionlint` earns its place: hand-editing a workflow to add a `with:` block is
the change most likely to break structure, and PyYAML parses a structurally
wrong file happily.

### Structural assertions

These catch the specific mistakes the happy path would miss:

- Every one of the five `astral-sh/setup-uv` steps carries
  `version: "0.12.24"`, and the count of `version:` keys under those steps
  equals the count of `setup-uv` steps. Assert with a count, not an eyeball.
- Each pinned SHA matches the tag in its own trailing comment. A reachable old
  SHA with a freshly bumped comment installs and passes every hook, while
  silently violating the tag-comment convention. Use a verifier that parses the
  pairs, refuses anything unparsed, and exits non-zero on any problem — a check
  that cannot fail verifies nothing:

  ```python
  import re, subprocess, sys, pathlib

  cfg = pathlib.Path(".pre-commit-config.yaml").read_text()
  entries = re.findall(r"^\s*-\s*repo:\s*(\S+)\s*$\n\s*rev:\s*(\S+)\s*(?:#\s*(\S+))?\s*$", cfg, re.M)
  if not entries:
      print("no remote repo entries parsed -- is the format right?", file=sys.stderr)
      sys.exit(2)

  bad = 0
  for repo, rev, tag in entries:
      problems = []
      if "://" in repo or repo.startswith("git@"):
          url = repo  # full URL or SCP form: ls-remote takes either as-is
      else:
          url = f"https://github.com/{repo}"
      if not re.fullmatch(r"[0-9a-f]{40}", rev):
          problems.append(f"rev={rev!r} is not a 40-char hex SHA")
      elif not tag:
          problems.append(f"pinned {rev} with no tag comment")
      else:
          out = subprocess.run(
              ["git", "ls-remote", url, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
              capture_output=True,
              text=True,
              check=True,
          ).stdout
          lines = [line for line in out.splitlines() if line]
          if not lines:
              problems.append(f"tag {tag} does not exist")
          elif lines[-1].split()[0] != rev:
              problems.append(f"{tag} is {lines[-1].split()[0]}, pinned {rev}")
      if problems:
          print(f"FAIL {repo}: " + "; ".join(problems))
          bad += 1
      else:
          print(f"ok   {repo}  {tag}  {rev}")

  print(f"\n{len(entries)} remote repo(s), {bad} problem(s)")
  sys.exit(1 if bad else 0)
  ```

  Run it twice. Before the pins land it must report four `FAIL` lines and
  exit 1; that proves it actually fails. After, it must report four `ok` lines
  and exit 0.

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
| remote repo with no `rev` key at all | fail, rule 1 |
| pinned `rev` with no trailing tag comment | fail, rule 1 |
| YAML alias resolving to a valid hex `rev` | pass: pre-commit resolves it to the same hex |
| YAML alias resolving to a tag, or an undefined alias | fail: tag is not a SHA; undefined is an error |
| CRLF line endings | pass: the parser handles structural values; the raw-line comment pass handles `\r` explicitly |
| repo entry with `rev` but no `hooks` | pass here: pre-commit itself rejects it loudly, so the guard needs no opinion |
| `setup-uv` step, `version:` missing, empty, `latest` or `latest-known` | fail, rule 2 |
| `setup-uv` step, range or wildcard (`>=0.12.10`, `~=0.12.10`, `0.12.x`, `0.12`) | fail, rule 2 |
| `setup-uv` step, unquoted `version: 0.12` (YAML float) | fail, rule 2: non-string fails the match |
| `uses: actions/checkout@<40-hex>` | pass, rule 3 |
| `uses: actions/checkout@v7` | fail, rule 3 |
| `uses: ./local-action` or `uses: docker://img:tag` | pass: not a git ref |
| `setup-uv` step, `version: "${{ env.UV_VERSION }}"` or `""` | fail, rule 2 |
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

- The four `uvx` invocations PR #6 pinned have no guard. A dropped `--no-build`
  or a floated version there is silent: Task 3 sees structured `with.version`
  inputs, not `run:` text. Extending rule 2 to the `uvx` forms would need
  shell-aware parsing and is out of scope.
- The action-SHA audit does not run on push to `main`. `zizmor` fires on pull
  requests and the weekly schedule, while `ci.yml` fires on push, so a direct
  push carrying a bad `uses:` reference sits unaudited until the next scheduled
  run. Normal flow goes through PRs, where it is caught.

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
- PyYAML, once added for Task 3, misses the weekly audit gate but not
  Dependabot. Each audit job exports with `--no-dev`, so a PyYAML CVE does not
  fail that job; but dev-group packages from `uv.lock` are already in this
  repo's dependency graph — verified via the SBOM export, which lists
  `hypothesis`, `pytest` and `basedpyright` — so Dependabot alerts would still
  fire for a PyYAML CVE, and the weekly `uv` version updates would propose the
  bump. The gap is a red gate in CI, not silent exposure. Widen the weekly
  export to include dev if a failing job is wanted on top of the alert.
- Composite actions, if any were added under `.github/actions/`, would escape
  both the hook's `files:` regex and rules 2 and 3, which only see workflows. None
  exist today, so there is nothing to guard yet; widen both if one appears.

## Not in this plan

Moving `pip-audit`, `pre-commit` and `zizmor` into `[dependency-groups]` for
`uv.lock` hash verification. Already in `TODO.md`; bigger change, not bundled.

## Rollback

Tasks 1 and 2 are single-line reverts. If a pinned SHA is wrong, revert that
`rev` and re-run `pre-commit run --all-files`. Task 1's pin/bump split means
reverting a bump does not un-pin anything. Task 3 is additive: delete the hook
registration and the script.
