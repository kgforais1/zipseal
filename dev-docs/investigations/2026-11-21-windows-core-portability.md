# Investigation: Windows core portability and cost

Date: 2026-11-21
Code: `feat/windows-build` at `a3b0d7f` (PR #26); `main` at `7dc0945`
Feeds: [`../plans/2026-11-02-gui-executables.md`](../plans/2026-11-02-gui-executables.md)
Phase 3, `TODO.md`, PR #26
Sources: the Greptile P1 review of PR #26, code inspection, and an
NVIDIA-hosted Kimi K3.1 Pro advisory review

## Question

Can the Windows GUI ship from the `build-windows` job in PR #26, and if not,
what would production-parity Windows support cost?

## Findings

| # | Finding | Evidence |
|---|---|---|
| 1 | The Windows app launches but cannot create archives. `collect.py` opens the input parent with `os.O_DIRECTORY` and walks with `os.fwalk(..., dir_fd=...)`/`os.stat(..., dir_fd=...)`; `sources.py` uses `O_DIRECTORY` and `os.open(..., dir_fd=...)`; `verify.py` and `output.py` use `O_NOFOLLOW`. Windows Python does not provide these. | Greptile P1 on PR #26; code inspection. The launch-only smoke would not catch it. |
| 2 | A path-based `os.scandir`/`os.lstat` rewrite can preserve basic behavior but not the descriptor-relative, component-by-component TOCTOU protection in `SPEC.md` §6.5–§6.7. | The chain checks in `collect.py`/`sources.py` rely on held directory descriptors and `st_dev`/`st_ino`. |
| 3 | The right boundary is a small filesystem backend abstraction, not a separate Windows collector/pipeline. Keep excludes/collisions, change detection, publication/rollback and archive logic shared; backends own walking, component open/stat, identity, exclusive create, verification reopen and close. Make `Collection.roots` opaque handles. | Kimi advisory; matches the existing module boundaries. |
| 4 | Production parity is roughly 15–25 person-days (3–5 focused weeks). A weak stdlib prototype is 4–7 days but must not ship under the current security claims. | Kimi estimate; phase table below. |
| 5 | Windows mechanics: `scandir`/`lstat` + `fstat`; treat all reparse points (symlink, junction, mount point) as unsafe; `CreateFileW` with `FILE_FLAG_OPEN_REPARSE_POINT`/`BACKUP_SEMANTICS` is not an `openat` replacement; full parity likely needs a tested `NtCreateFile` + `OBJECT_ATTRIBUTES.RootDirectory` spike; `O_EXCL` and `os.link` survive; `0o600` is not a POSIX ACL. | Kimi advisory. |
| 6 | Add `windows-2025` to the full pytest matrix and an extracted-artifact archive-create/decrypt-open smoke. Launch-only must not be the release gate. | Kimi advisory; the current `check-test` matrix is Ubuntu/macOS. |

## Estimate

| Phase | Days | Work |
|---|---:|---|
| Design / native spike | 2–4 | Backend interface; prove handles, identity and reparse behavior |
| Collection + walking | 2–4 | `collect.py`, backend root/walk handles |
| Source opening | 3–5 | `sources.py`; rooted traversal and race tests |
| Output + verification | 2–3 | `output.py`, `verify.py`; minor `write.py`/`pipeline.py` |
| Tests | 4–6 | Existing suites plus Windows replacement/reparse races |
| CI + packaging/acceptance/docs | 2–4 | `windows-2025` matrix, artifact smoke, PR #26, `SPEC.md` |

Total: **15–25 person-days**, or **3–5 focused weeks** for one person.
Biggest risks: rooted Windows opens, identity across NTFS/ReFS/network
volumes, sharing/antivirus interference, and ACL semantics.

## Decision

- The Windows artifact is **deferred** (2026-11-21). PR #26 stays a draft as
  the build half; it must not publish or attach a Windows artifact until the
  backend and tests land.
- Phase 4 Linux proceeds first; the POSIX core already supports it.
- If Windows is picked up, do the backend abstraction and the native spike
  before any packaging claim. A reduced Windows subset needs an explicit
  weaker-threat-model decision in `SPEC.md`, not a silent port.
- `TODO.md` carries the deferred item and links this file.

## Method

Greptile reviewed PR #26 and reported the P1 (`Windows cannot create
archives`). Code inspection confirmed the POSIX-only primitives. An
NVIDIA-hosted Kimi K3.1 Pro advisory review read the core and returned the
recommendation, estimate, mechanics and test list above. No code was changed
for this investigation.
