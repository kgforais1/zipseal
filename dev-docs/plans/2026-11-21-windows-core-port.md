# Plan: Windows filesystem backend

Date: 2026-11-21
Status: draft
Linked: `TODO.md` "Port the core's filesystem layer to Windows…";
[investigation](../investigations/2026-11-21-windows-core-portability.md);
PR #26 (draft build half)

## Goal

Make the frozen Windows GUI able to create, verify and open archives with the
same safety properties as macOS/Linux: no symlink or reparse traversal, held
identity checks, no plaintext, and no clobbering. Keep the business logic
shared; replace only the OS primitives.

## Non-goals

- No path-based `os.scandir` implementation that claims `SPEC.md` §6.5 parity.
- No Windows arm64, Store/MSIX or signing work here.
- No change to the macOS/Linux behavior.

## Decisions

1. **Filesystem backend abstraction.** A small internal interface with POSIX
   and Windows implementations; `Collection.roots` becomes opaque handles.
   Backends own walking, component open/stat, identity, exclusive create,
   verification reopen and close. Excludes/collisions, change detection,
   publication/rollback and archive logic stay shared.
2. **Reparse points.** Treat every reparse point (symlink, junction, mount
   point, other) as unsafe by default; disable `--follow-symlinks` on Windows
   until supported. Detect `FILE_ATTRIBUTE_REPARSE_POINT`/`st_reparse_tag`, not
   only `S_ISLNK`.
3. **Native spike before implementation.** Prove `CreateFileW` with
   `FILE_FLAG_OPEN_REPARSE_POINT`/`BACKUP_SEMANTICS` and
   `GetFileInformationByHandle`; if component-relative opens need
   `NtCreateFile` + `OBJECT_ATTRIBUTES.RootDirectory`, record the failing
   behavior and the design here before writing the backend.
4. **ACLs.** `0o600` is not a POSIX ACL on Windows. Implement a restrictive
   output ACL or re-express the `SPEC.md` requirement explicitly; do not
   silently weaken it.
5. **Tests before packaging.** Add `windows-2025` to the full pytest matrix and
   an extracted-artifact archive smoke (create/decrypt/open). Launch-only
   never passes.

## Phases

- [ ] Design/native spike; record findings here.
- [ ] Backend interface + opaque root handles; POSIX backend unchanged.
- [ ] Windows collection/walking; reparse defaults; identity checks.
- [ ] Windows source opening and race tests.
- [ ] Windows output create/verify/reopen; ACL decision; publication.
- [ ] Windows tests: archive variants, replacement races, reparse points,
      no-clobber, hardlink rollback, Unicode/long paths, output-inside-input.
- [ ] CI: `windows-2025` in `check-test`; artifact archive smoke in
      `release.yml`.
- [ ] Packaging/acceptance/docs: PR #26, `SPEC.md`, `releasing.md`, manual
      acceptance.

## Test list

- [ ] `windows-2025` × Python 3.11/3.13 runs the fast suite.
- [ ] Basic, split and `--hide-names` archives are created and decrypt/open.
- [ ] Source/temp/final reparse points are rejected; junction tests are
      mandatory, symlink tests conditional on privilege.
- [ ] File and parent replacement, same-size swaps, growth/shrink and
      final-name races fail closed.
- [ ] Output no-clobber, `--force` rollback and hardlink publication.
- [ ] Unicode/long paths and output-inside-input.
- [ ] Extracted frozen artifact creates and opens an archive; launch-only
      does not pass.

## Estimate

15–26 person-days (3–5 focused weeks); see the investigation's phase table.

## Risks

Rooted Windows opens; identity across NTFS/ReFS/network volumes; sharing/AV
interference; ACL semantics.

## Review changes

- 2026-11-21: Draft from the investigation and the Greptile P1; no
  implementation started.
