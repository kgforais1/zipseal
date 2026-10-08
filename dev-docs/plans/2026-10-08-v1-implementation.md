# Plan: zipseal v1 implementation

Date: 2026-10-08
Status: draft
Linked: `TODO.md` → "Implement v1"; design in [`SPEC.md`](../../SPEC.md)

## Goal

Build the `zipseal` CLI described in `SPEC.md` §4–§6. It writes files and
folders into AES-256 zips, optionally split into parts that each open on their
own and never exceed `--max-size`. v1 ends with a tested `0.1.0` release that
someone can install with `uv tool install`.

## Out of scope

- CI. It is a separate `TODO.md` item.
- `--legacy-zipcrypto`, `--format 7z`, `--oversize=volumes` and `--tight`.
- Extraction, a GUI, and splitting one file across parts.
- Windows support beyond "the archives open in 7-Zip". The CLI is tested on
  macOS and Linux only.

## Findings that change the spec

A spike on 2026-10-08 against `stream-zip` 0.0.84 and `stream-unzip` 0.0.101
found three things `SPEC.md` gets wrong or leaves open. Phase 0 fixes the spec.

1. **AE-2 entries carry no CRC.** `stream-zip` writes AES entries with vendor
   version 2 (AE-2), strength 3 (AES-256), method 99, and a CRC field of 0.
   Integrity comes from the 10-byte HMAC-SHA1 instead. `SPEC.md` §6.6 says
   verification "checks the CRC". It cannot. Verification will instead rely on
   the HMAC check that `stream-unzip` performs. It will also compare a SHA-256
   of each decrypted entry with a SHA-256 taken while the source was read.
2. **A stored outer entry needs its size and CRC up front.**
   `NO_COMPRESSION_32/64` take `(uncompressed_size, crc_32)` as arguments.
   The `--hide-names` outer entry is an inner zip that is still being
   generated, so neither value is known. `SPEC.md` §6.7 says the outer zip is
   "stored". It will instead use `ZIP_64` with deflate level 0. Level 0 emits
   stored deflate blocks, costing 5 bytes per block of up to 65,535 bytes,
   and needs no size or CRC in advance.
3. **Compression level is per call, and the library default is 9.** Level is
   set through `get_compressobj` on `stream_zip()` or through
   `ZIP_AUTO(size, level=…)`. zipseal must pass its own level, which defaults
   to 6.

Measured archive sizes, one entry each, password set:

| Input | `ZIP_32` total | `ZIP_64` total |
|---|---|---|
| empty file | 186 B | 318 B |
| 100,000 random bytes | 100,219 B | 100,351 B |
| 1,000,000 random bytes | 1,000,496 B | 1,000,628 B |

The 1 MB row matches the "5 bytes per 16 KiB block" expansion term in
`SPEC.md` §6.2 for incompressible data at level 9.

## Approach

Pure Python 3.11+, packaged with `uv` in a `src/` layout. `stream-zip` writes
and `stream-unzip` verifies (see `SPEC.md` §3). Each module in `SPEC.md` §5
owns one stage. Data flows one way:
`cli → collect → plan → write → verify → finalize`.

The hard part is the size cap, and Phase 4 is built around it. The rest is
careful plumbing. Every phase ends with passing tests and a commit, so any
phase boundary is a safe place to stop.

### Alternatives considered

| Option | Why not chosen |
|---|---|
| `pyzipper` | Unmaintained since 2022. Its `zipfile`-style API hides the byte stream, so exact part sizes would be hard to count. |
| Shelling out to `7zz` | Spanned volumes are not self-contained, and it adds a binary dependency. Kept as a later backend. |
| Go or Rust | The Python libraries already do AE-2 and Zip64 streaming. No speed requirement justifies a rewrite. |
| Two-pass exact sizing in v1 | Doubles the I/O and needs plaintext temp files or a lot of RAM. Deferred as `--tight`. |

## Decisions made in this plan

These fill gaps in `SPEC.md`. Phase 0 copies each one into the spec.

| Topic | Decision |
|---|---|
| Single-part naming | If the run produces one part, it is named exactly `-o`, for example `bundle.zip`, even when `--max-size` is set. Two or more parts are named `bundle-partNN-of-MM.zip`. Use three-digit `NNN` when there are more than 99 parts. |
| Output inside an input | If the output path is inside an input folder, the walker skips the output files and `*.partial` files from this run. |
| `--force` scope | `--force` overwrites only the exact file names this run produces. Other files that look like old parts are listed as a warning, never deleted. |
| Existing-output check | Before writing, the run fails with exit 3 if `bundle.zip` or any `bundle-part*-of-*.zip` exists, unless `--force` is set. |
| `--dry-run` part count | Planning uses worst-case bounds, so dry-run prints "at most N parts". |
| Timestamps | mtimes before 1980-01-01 are clamped to that date, and mtimes after 2107-12-31 to that date. Each clamp prints one warning that names the file. |
| Undecodable file names | Names that do not decode as UTF-8 stop the run with exit 2 and a list of the bad paths. |
| Interrupt | Ctrl-C deletes this run's `.partial` files and exits with 130. |
| Password encoding | Passwords are encoded as UTF-8. Generated passwords use only ASCII letters and digits. A non-ASCII password prints a warning that some tools may not open the archive. |
| Password storage | The password is held as `str` in memory for the run. Python cannot reliably wipe memory. `SPEC.md` §7 records this as a known limit. |
| Dependency pins | `stream-zip>=0.0.84,<0.1` and `stream-unzip>=0.0.101,<0.1`. `uv.lock` is committed. Pre-1.0 releases can break APIs, so upgrades are deliberate. |
| Type checking | `basedpyright` in standard mode, run by pre-commit. |

## Proposed file changes

```
pyproject.toml          package metadata, console script, deps, pytest config
uv.lock                 committed lockfile
.python-version         3.12 for development; requires-python >=3.11
src/zipseal/__init__.py version string
src/zipseal/__main__.py python -m zipseal
src/zipseal/cli.py      argparse, password sources, exit codes, error printing
src/zipseal/sizes.py    parse "25MB" / "10MiB" / "2G" / raw bytes
src/zipseal/collect.py  FileEntry, walk, excludes, symlinks, collisions
src/zipseal/plan.py     bound(), part assignment for path and size order
src/zipseal/write.py    stream one part, count bytes, .partial files, 0600
src/zipseal/verify.py   decrypt, HMAC, SHA-256 and path-set checks
src/zipseal/output.py   part naming, existing-output checks, final rename, cleanup
src/zipseal/errors.py   exception types mapped to exit codes
tests/conftest.py       tree builders, password fixture, 7zz skip marker
tests/test_*.py         one file per module, plus test_cli.py end to end
user-docs/*.md          quick start, CLI reference, opening archives, security
dev-docs/investigations/2026-10-08-stream-zip-spike.md   the findings above, in full
```

## Phases and checklist

### Phase 0: Spec corrections

- [ ] Write the spike results to `dev-docs/investigations/2026-10-08-stream-zip-spike.md`.
- [ ] Update `SPEC.md` §6.6 to say HMAC plus SHA-256, not CRC.
- [ ] Update `SPEC.md` §6.7 to say the outer entry uses deflate level 0, not stored.
- [ ] Copy the "Decisions made in this plan" table into the relevant `SPEC.md`
      sections.
- [ ] Add §6.8 "Part admission" to `SPEC.md` once Phase 4 settles it.

### Phase 1: Scaffold

- [ ] Run `uv init --package --lib`, then trim it to the layout above. Add a
      `zipseal = "zipseal.cli:main"` console script.
- [ ] Add runtime deps `stream-zip` and `stream-unzip`. Add dev deps `pytest`,
      `hypothesis` and `basedpyright`.
- [ ] Configure pytest with a `slow` marker that is skipped unless `-m slow`
      is passed, and a `sevenzip` marker that skips when `7zz` is missing.
- [ ] Add `basedpyright` to `.pre-commit-config.yaml` as a local hook running
      `uv run basedpyright`.
- [ ] Write `errors.py`. `UsageError` maps to exit 1, `InputError` to 2,
      `WriteError` and `VerifyError` to 3, and `KeyboardInterrupt` to 130.
- [ ] Write `sizes.py`. `MB` means 10^6 and `MiB` means 2^20. A bare `G`
      means 10^9. Bare numbers are bytes. Reject zero, negatives and
      fractions of a byte.
- [ ] Write the argparse skeleton in `cli.py` with every `SPEC.md` §4 option
      except `--legacy-zipcrypto`. The password options form a mutually
      exclusive group.
- [ ] Implement the password sources:
  - `--password-prompt`, the default, asks twice with `getpass` and requires
    a match. With no TTY on stdin it fails with exit 1 and suggests
    `--password-env` or `--password-file`.
  - `--password-env VAR` fails if `VAR` is unset or empty.
  - `--password-file PATH` reads the first line and strips the trailing
    `\n` or `\r\n`. It warns when the mode allows group or other reads. It
    fails on an empty first line.
  - `--generate-password` produces 24 characters from `secrets.choice` over
    ASCII letters and digits. It prints the password once to stderr, after
    the archive is verified, so a failed run never shows a password for an
    archive that does not exist.
- [ ] Reject an empty password. Warn when a typed password is shorter than
      12 characters.
- [ ] Tests:
  - Size parsing, valid and invalid.
  - Each password source, using `monkeypatch` for `getpass` and the
    environment.
  - Mismatched prompts.
  - A password file that is readable by others.
  - The password never appears in stdout, stderr or exception text. Check
    this with `capsys` on both success and failure paths.

### Phase 2: Collect

- [ ] Define `FileEntry(src: Path, arcname: str, size: int, mtime: datetime,
      mode: int, is_dir: bool)` as a frozen dataclass.
- [ ] Map archive paths per `SPEC.md` §6.1. A folder keeps its own name as
      the top level. A file goes to the root. Separators are always `/`.
      Reject `..`, absolute paths and empty components.
- [ ] Apply excludes:
  - Defaults are `.DS_Store`, `._*` and `Thumbs.db`.
  - `--exclude` is repeatable. A pattern matches the base name, or the full
    archive path if it contains `/`.
  - `--no-default-excludes` turns off the defaults.
- [ ] Skip symlinks with one warning each, unless `--follow-symlinks` is set.
      When following, detect directory cycles by `(st_dev, st_ino)` and fail
      with exit 2.
- [ ] Skip sockets, FIFOs and device files with a warning.
- [ ] Store empty folders as directory entries.
- [ ] Detect collisions and fail with exit 2, listing every colliding
      archive path and its sources. Compare case-insensitively too, so an
      archive that would collide when extracted on macOS or Windows is
      caught. Fail on case-only collisions as well.
- [ ] Skip the output files and this run's `.partial` files when the output
      sits inside an input.
- [ ] Clamp timestamps per the decisions table.
- [ ] Implement `--dry-run` listing of the collected entries. Part grouping
      is added in Phase 4.
- [ ] Tests:
  - Nested trees and mixed file and folder inputs.
  - Excludes and their defaults.
  - Symlink skip and follow, plus a symlink cycle.
  - Collisions, including case-only collisions.
  - Unicode names in NFC and NFD forms. Archive paths are normalized to NFC.
  - Empty files and folders, an output inside an input, and undecodable
    names on Linux.

### Phase 3: Single archive

- [ ] In `write.py`, stream the entries through `stream_zip` with the
      password and `get_compressobj` set to `--level`:
  - Files use `ZIP_AUTO(size, level)`.
  - Directories use `NO_COMPRESSION_32(0, 0)` with a trailing `/` in the
    name.
  - Mode bits are `S_IFREG | (st_mode & 0o777)` for files and
    `S_IFDIR | 0o755` for folders.
- [ ] Hash each file with SHA-256 while it is read, by wrapping the chunk
      iterator. Keep the hashes in memory for `verify.py`.
- [ ] Detect a file whose size changed between collect and read, and fail
      with exit 3. `stream-zip` raises `UncompressedSizeIntegrityError` for
      this. Map that to a clear message that names the file.
- [ ] Open output with `os.open(path, O_WRONLY | O_CREAT | O_EXCL, 0o600)`
      under the `.partial` name. Call `fsync` before closing.
- [ ] In `verify.py`, stream the part through `stream_unzip` with the
      password. Drain every entry so the HMAC is checked. Compare the
      SHA-256 of each entry with the recorded hash. Check that the set of
      archive paths equals the planned set.
- [ ] Rename `.partial` to the final name only after verification passes.
- [ ] Tests:
  - A round trip extracts with `stream-unzip` byte for byte.
  - A wrong password fails with exit 3.
  - A corrupted byte in the ciphertext fails verification.
  - The output mode is `0600`.
  - An existing output without `--force` fails with exit 3.
- [ ] Manual check: the archive opens in Keka and in Finder (Archive Utility)
      on macOS 26. Record the result in the Phase 3 commit message.

### Phase 4: Split

This phase starts with a short spike, because the admission rule depends on
`stream-zip` internals.

- [ ] Spike: measure how much output `stream_zip` buffers when it pulls the
      next member from the input iterator. Then choose one of these designs
      and record the choice and evidence in `dev-docs/investigations/`.
  - **A. Exact counting.** Wrap the object returned by `get_compressobj` so
    it counts the bytes from `compress()` and `flush()`. AES-CTR does not
    change length. A member's exact size is then its local header plus the
    AES overhead (28 bytes), the compressed bytes, and its data descriptor.
    This is the preferred design. It depends on `stream-zip` calling only
    `compress` and `flush`, so a test must pin that behavior.
  - **B. Margin.** Admit the next member only if `emitted + chunk_size +
    bound(next) + central_dir(all admitted + next) + EOCD ≤ max_size`. This
    is safe whatever the buffering is, but wastes up to one `chunk_size`
    per part. Lower `chunk_size` to 16 KiB to limit the waste.
- [ ] Implement `bound(e)` in `plan.py` from `stream-zip`'s own header
      structs. Always use Zip64 field sizes, because the bound must hold
      whichever method `ZIP_AUTO` picks. Include deflate worst case, local
      header, extended timestamp extra, AES extra, salt, verifier, MAC, data
      descriptor and central directory entry.
- [ ] Before writing anything, fail with exit 2 if any single entry's bound
      plus the EOCD exceeds `--max-size`. Name the file, and suggest the 7-Zip
      spanned command from `SPEC.md` §2.
- [ ] Implement admission and part rollover. The member iterator decides,
      before yielding each entry, whether the entry fits in the current part.
      If it does not, the iterator ends the current `stream_zip` call and the
      writer opens the next part.
- [ ] Name parts `bundle-partNN.zip.partial` while writing. Rename them to
      `bundle-partNN-of-MM.zip` after every part verifies. With one part, use
      the plain name from the decisions table.
- [ ] Verify that each part opens without the others, that its size on disk
      is at most `--max-size`, and that the union of paths across parts
      equals the planned set with no duplicates.
- [ ] Implement `--order path`, which is the default sorted by archive path.
      Implement `--order size` as first-fit-decreasing by bound. With FFD,
      several parts are open at once in the plan, but they are still written
      one at a time.
- [ ] Extend `--dry-run` to show the planned parts as "at most N parts".
- [ ] Tests:
  - Random incompressible data with caps of 1 MB, 5 MB and 25 MB never
    produces a part over the cap.
  - A `hypothesis` property test: for random file-size lists, random name
    lengths and random caps, every part is at most the cap and every file
    lands in exactly one part.
  - Highly compressible data fills parts well. A smoke test checks that a
    part is at least 50% full when more files remain.
  - Each part extracts alone.
  - An oversized file fails with exit 2 and writes nothing.
  - Both orders are deterministic across two runs.

### Phase 5: Safe writes and failure handling

- [ ] Wrap the whole run in one cleanup scope. On any exception or Ctrl-C,
      delete every `.partial` file this run created and leave other files
      alone.
- [ ] Rename only after all parts verify. Do the renames last, in part order.
- [ ] Before the first byte is written, check that the output directory
      exists and is writable. Report a full disk (`ENOSPC`) clearly as exit 3.
- [ ] Implement `--force` and the existing-output warning from the decisions
      table.
- [ ] Implement `--no-verify`, which skips verification but still checks
      sizes against the cap.
- [ ] Tests:
  - A failure injected mid-part leaves no `.partial` files and no final
    files.
  - A failure injected in verification leaves no `.partial` files.
  - A simulated Ctrl-C exits with 130 and leaves no `.partial` files.
  - `--force` overwrites only its own targets.

### Phase 6: Hide names

- [ ] Write each part as an inner `stream_zip` with no password and the
      chosen level. Feed its chunks as the content of one outer entry named
      `payload.zip`, with mtime 1980-01-01 and method `ZIP_64`. Pass a
      level-0 `get_compressobj` and the password on the outer call.
- [ ] Disable extended timestamps on the outer call, so the outer entry
      carries no real time.
- [ ] Add the fixed outer overhead and level-0 block overhead to the bound.
- [ ] Verify both layers. Decrypt the outer entry, stream it into
      `stream_unzip` without a password, and check the inner SHA-256 values.
- [ ] Tests:
  - Listing a part shows only `payload.zip`. Use `stream-unzip` for this,
    and also `7zz l` when it is installed.
  - The inner round trip is byte-identical.
  - No part exceeds the cap.
  - No temp files appear in the output directory or `$TMPDIR` during the run.

### Phase 7: Polish and release

- [ ] Implement `--manifest`. It adds `MANIFEST.txt` inside each part,
      listing every archive path and its part number. Part 1 is written
      before later assignments are known, because Phase 4 assigns parts from
      real compressed sizes. So with `--manifest`, assign every entry to a
      part from bounds alone, before writing. Packing is looser, but the full
      manifest is known up front, and its bound is reserved in each part's
      budget.
- [ ] Print progress on stderr only when stderr is a TTY. Print one final
      summary line listing the parts and their sizes.
- [ ] Write `user-docs/`: quick start, CLI reference, opening archives on
      each OS, and security notes from `SPEC.md` §7. Add a short root
      `README.md` that links to them.
- [ ] Run the slow tests: a file over 4 GiB (Zip64) and 10,000 small files.
- [ ] Run the `7zz` interop tests (`brew install sevenzip`). `7zz t` must
      accept every part.
- [ ] Manual checks: split output opens in Keka and in Finder, and on
      Windows with 7-Zip if a machine is available. Record the results.
- [ ] Set the version to `0.1.0`. Move the `CHANGELOG.md` entries to
      `[0.1.0]` and tag `v0.1.0`.
- [ ] Run the completion steps in `dev-docs/README.md`.

## Verification

The plan is complete when all of these hold:

- [ ] `uv run pytest` passes, and `uv run pytest -m slow` passes once on macOS.
- [ ] `pre-commit run --all-files` passes, including `basedpyright`.
- [ ] Every test listed in `SPEC.md` §8 has a matching test, or a recorded
      reason why it changed.
- [ ] `uv tool install .` puts a working `zipseal` on the PATH.
- [ ] The manual Keka, Finder and 7-Zip checks are recorded.
- [ ] `SPEC.md` matches the built behavior.

## Open questions

These come from `SPEC.md` §9, with a recommendation for each. They need a
user decision before the phase listed.

- [ ] Should a file over the cap be split with 7-Zip in v1? The
      recommendation is no. Keep it an error with a 7-Zip hint, as §6.4
      says. Needed before Phase 4.
- [ ] Is `--legacy-zipcrypto` needed? The recommendation is no. Drop it from
      the v1 help text. Needed before Phase 1.
- [ ] Should the manifest live inside or beside the parts? The
      recommendation is inside only. A manifest beside the parts leaks the
      names that `--hide-names` exists to hide. Needed before Phase 7.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `stream-zip` buffering makes exact counting unreliable | med | high | The Phase 4 spike chooses A or B on evidence. The property test gates both. |
| A `stream-zip` 0.0.x release changes internals that design A relies on | med | med | Pin `<0.1`, commit `uv.lock`, and keep a test that fails loudly if the compressobj contract changes. |
| Finder or Archive Utility fails on Zip64 or split parts | low | med | Manual check in Phases 3 and 7. Document the fallback to Keka or `tar -xf`. |
| The password leaks through a traceback | low | high | One top-level handler prints sanitized messages. Tests assert that the password never appears in output. |
| Non-ASCII passwords differ between tools | med | low | Warn. Generated passwords are ASCII-only. Add a `7zz` test with a non-ASCII password. |
| Text-heavy inputs leave parts half-empty because the bound is loose | med | low | Accepted for v1. `--tight` is in `TODO.md` "Later". |

## Completion steps

Follow the lifecycle in [`dev-docs/README.md`](../README.md#completion-steps).
