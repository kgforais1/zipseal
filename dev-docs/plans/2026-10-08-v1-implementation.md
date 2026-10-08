# Plan: zipseal v1 implementation

Date: 2026-10-08
Status: in-progress
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

## Findings that changed the spec

A spike on 2026-10-08 against `stream-zip` 0.0.84 and `stream-unzip` 0.0.101,
and a Grok 4.7 review the same day, found the problems below. `SPEC.md` was
corrected on 2026-10-08. Full evidence is in
[`../investigations/2026-10-08-stream-zip-spike.md`](../investigations/2026-10-08-stream-zip-spike.md).

1. **AE-2 entries carry no CRC.** `stream-zip` writes AES entries with vendor
   version 2 (AE-2), strength 3 (AES-256), method 99, and a CRC field of 0.
   Integrity comes from the 10-byte HMAC-SHA1 instead. `SPEC.md` §6.6 says
   verification "checks the CRC". It cannot. Verification will instead rely on
   the HMAC check that `stream-unzip` performs. It will also compare a SHA-256
   of each decrypted entry with a SHA-256 taken while the source was read.
2. **A stored outer entry needs its size and CRC up front.**
   `NO_COMPRESSION_32/64` take `(uncompressed_size, crc_32)` as arguments.
   The `--hide-names` outer entry is an inner zip that is still being
   generated, so neither value is known. The outer entry instead uses deflate
   level 0, which emits stored deflate blocks at 5 bytes per block of up to
   65,535 bytes and needs no size or CRC in advance. It uses `ZIP_32`
   unless the part could pass 4 GiB.
3. **`ZIP_AUTO` ignores `get_compressobj` and does not check sizes.** It
   builds its own compressor, so a compressor wrapper passed to
   `stream_zip()` never sees a byte. It also archives a file that grew after
   collection at its new size. Both were confirmed by test. zipseal
   therefore chooses `ZIP_32` or `ZIP_64` explicitly and counts the bytes it
   reads. `UncompressedSizeIntegrityError` is raised only by
   `NO_COMPRESSION_*`.
4. **The library default level is 9.** zipseal passes its own level, which
   defaults to 6, through `get_compressobj`.
5. **The original admission rule could overflow the cap.** It did not
   reserve the central-directory entries of files already in the part. Those
   entries are written only when the part closes. `SPEC.md` §6.2 now
   reserves them.
6. **Verification must restrict encryption types.** By default
   `stream_unzip` also accepts ZipCrypto and AE-1. Verification passes only
   AE-2 AES-256. `stream_zip` takes the password as `str`, and
   `stream_unzip` takes it as `bytes`.
7. **`stream-zip` pulls the next member only after the current member is
   finished.** Output is re-chunked to `chunk_size` (65,536 by default), with
   a flush after each local header.
8. **The original deflate bound was not a guaranteed bound.** `SPEC.md` §6.2
   now uses zlib's own bound for raw deflate with `memLevel=8`. Level 0 does
   not always fill 65,535-byte blocks, so the outer layer under
   `--hide-names` uses the same bound.
9. **Explicit `ZIP_32` fails at 65,536 entries, and extended timestamps fail
   after January 2038.** Entries from the 65,535th onward use `ZIP_64`, and
   extended timestamps are off.
10. **`stream-unzip` ignores the central directory.** An archive with a
    corrupt end record still decrypts. Verification adds a structural check.

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

These fill gaps in `SPEC.md`. Phase 1 copies each one into the spec.

| Topic | Decision |
|---|---|
| Single-part naming | If the run produces one part, it is named exactly `-o`, for example `bundle.zip`, even when `--max-size` is set. Two or more parts are named `bundle-partNN-of-MM.zip`. Use three-digit `NNN` when there are more than 99 parts. |
| Output inside an input | If the output path is inside an input folder, the walker skips the output name, any existing part name for it (same pattern as the existing-output check), and `*.partial` files. |
| `--force` scope | `--force` replaces only the exact file names this run produces, using the backup-and-restore flow in `SPEC.md` §6.5. Other files that look like old parts are listed as a warning, never deleted. |
| Existing-output check | Before writing, the run fails with exit 3 if `bundle.zip` exists, or any file matching `bundle-part` + digits + `-of-` + digits + `.zip`, unless `--force` is set. Other names are never matched. |
| `--dry-run` part count | Planning uses worst-case bounds, so dry-run prints "at most N parts". |
| Timestamps | Extended timestamps are off (`SPEC.md` §6.2). DOS timestamps in local time are clamped to 1980-01-01 00:00:00 through 2107-12-31 23:59:58. Each clamp prints one warning that names the file. |
| Undecodable file names | Names that do not decode as UTF-8 stop the run with exit 2 and a list of the bad paths. |
| Interrupt | Ctrl-C deletes this run's `.partial` files and exits with 130. |
| Generated password timing | `--generate-password` prints the password once, to stderr, after every part has passed verification (or the size check under `--no-verify`) and immediately before publication. A run that fails earlier prints no password. If publication then fails and rolls back, the run says plainly that no archive was written. |
| Case-insensitive collisions | Compare archive paths after NFC normalization and `str.casefold()`. |
| Manifest size | Part numbers in the manifest are zero-padded to the digit count of the number of entries, so the manifest's exact size is known before packing and does not depend on assignments. If the manifest's bound plus any single entry exceeds the cap, the run fails with exit 2. |
| `MANIFEST.txt` collision | If an input already maps to `MANIFEST.txt` at the archive root, `--manifest` fails with exit 2. |
| Password encoding | Passwords are encoded as UTF-8. Generated passwords use only ASCII letters and digits. A non-ASCII password prints a warning that some tools may not open the archive. |
| Password storage | The password is held as `str` in memory for the run. Python cannot reliably wipe memory. `SPEC.md` §7 records this as a known limit. |
| Dependency pins | `stream-zip>=0.0.84,<0.1` and `stream-unzip>=0.0.101,<0.1`. `uv.lock` is committed. Pre-1.0 releases can break APIs, so upgrades are deliberate. |
| Type checking | `basedpyright` in standard mode, run by pre-commit on the whole package (`pass_filenames: false`). |

## Proposed file changes

```
pyproject.toml          package metadata, console script, deps, pytest config
uv.lock                 committed lockfile
.python-version         3.12 for development; requires-python >=3.11
src/zipseal/__init__.py version string
src/zipseal/__main__.py python -m zipseal
src/zipseal/cli.py      argparse, exit codes, error printing
src/zipseal/passwords.py password sources; Password hides its value from repr()
src/zipseal/sizes.py    parse "25MB" / "10MiB" / "2G" / raw bytes
src/zipseal/collect.py  FileEntry, walk, excludes, symlinks, collisions
src/zipseal/plan.py     bound(), part assignment for path and size order
src/zipseal/write.py    stream one part, count bytes, .partial files, 0600
src/zipseal/verify.py   decrypt, HMAC, SHA-256 and path-set checks
src/zipseal/zipcheck.py parse end records and central directory; compare with writer records
src/zipseal/output.py   part naming, existing-output checks, final rename, cleanup
src/zipseal/errors.py   exception types mapped to exit codes
tests/conftest.py       tree builders, password fixture, 7zz skip marker
tests/test_*.py         one file per module, plus test_cli.py end to end
user-docs/*.md          quick start, CLI reference, opening archives, security
dev-docs/investigations/2026-10-08-stream-zip-spike.md   the findings above, in full
```

## Phases and checklist

### Phase 0: Spec corrections

- [x] Write the spike results to `dev-docs/investigations/2026-10-08-stream-zip-spike.md`.
- [x] Correct `SPEC.md` §4 size suffixes, §6.2 admission, §6.3 ordering
      modes, §6.5 safe writes, §6.6 verification, §6.7 outer layer, §7
      security notes, and the §8 test wording.

### Phase 1: Scaffold

- [x] Run `uv init --package --lib`, then trim it to the layout above. Add a
      `zipseal = "zipseal.cli:main"` console script.
- [x] Add runtime deps `stream-zip` and `stream-unzip`. Add dev deps `pytest`,
      `hypothesis` and `basedpyright`.
- [x] Configure pytest with a `slow` marker that is skipped unless `-m slow`
      is passed, and a `sevenzip` marker that skips when `7zz` is missing.
- [x] Add `basedpyright` to `.pre-commit-config.yaml` as a local hook running
      `uv run basedpyright` with `pass_filenames: false` and
      `files: ^(src|tests)/`, so it always checks the whole package.
- [x] Copy the decisions-table rows that are not yet in `SPEC.md` into the
      relevant sections: single-part naming, output inside an input,
      `--force` scope, the existing-output check, `--dry-run` part count,
      timestamp clamping, undecodable names, interrupt, generated password
      timing, case-insensitive collisions, the `MANIFEST.txt` collision, and
      password encoding and storage. Size suffixes, manifest padding and the
      `getpass` fallback are already in the spec.
- [x] Write `errors.py`. `UsageError` maps to exit 1, `InputError` to 2,
      `WriteError` and `VerifyError` to 3, and `KeyboardInterrupt` to 130.
- [x] Write `sizes.py` per `SPEC.md` §4. `KB`/`MB`/`GB`/`TB` and bare
      `K`/`M`/`G`/`T` are powers of 10. `KiB`/`MiB`/`GiB`/`TiB` are powers of
      2. Suffixes are case-insensitive. Bare numbers are bytes. Reject
      unknown suffixes, trailing junk, zero, negatives and fractions of a
      byte.
- [x] Write the argparse skeleton in `cli.py` with every `SPEC.md` §4 option
      except `--legacy-zipcrypto`. The password options form a mutually
      exclusive group.
- [x] Implement the password sources:
  - `--password-prompt`, the default, asks twice with `getpass` and requires
    a match. With no TTY on stdin it fails with exit 1 and suggests
    `--password-env` or `--password-file`. Turn `getpass.GetPassWarning`
    into an error with a `warnings` filter, so a terminal that cannot hide
    input stops the run (exit 1) before any input is read.
  - `--password-env VAR` fails if `VAR` is unset or empty.
  - `--password-file PATH` reads the first line and strips the trailing
    `\n` or `\r\n`. It warns when the mode allows group or other reads. It
    fails on an empty first line.
  - `--generate-password` produces 24 characters from `secrets.choice` over
    ASCII letters and digits. It prints at the moment given in the decisions
    table.
- [x] Reject an empty password. Warn when a typed password is shorter than
      12 characters.
- [x] Tests:
  - Size parsing, valid and invalid.
  - Each password source, using `monkeypatch` for `getpass` and the
    environment.
  - Mismatched prompts.
  - A `GetPassWarning` from `getpass` exits 1 without reading or printing
    anything.
  - A password file that is readable by others.
  - A typed or supplied password never appears in stdout, stderr or
    exception text, on success or failure. Check this with `capsys`.
  - A generated password appears exactly once on stderr on success, and
    never on failure.

### Phase 2: Collect

- [x] Define `FileEntry(root: int, relparts: tuple[str, ...], arcname: str,
      size: int, mtime: datetime, mode: int, is_dir: bool,
      chain: tuple[tuple[int, int], ...])` as a frozen dataclass. `root`
      indexes a directory descriptor opened once per input and held for the
      run. `chain` holds `(st_dev, st_ino)` for every directory between the
      root and the entry, and for the entry itself (`SPEC.md` §6.5). File
      inputs use their parent folder as the root.
- [x] Open roots with `O_DIRECTORY`, adding `O_NOFOLLOW` unless
      `--follow-symlinks` is set (the two traversal policies in `SPEC.md`
      §6.5).
- [x] Walk with `os.fwalk` from each root descriptor. Pass
      `follow_symlinks=True` only under `--follow-symlinks`.
- [x] Map archive paths per `SPEC.md` §6.1. A folder keeps its own name as
      the top level. A file goes to the root. Separators are always `/`.
      Reject `..`, absolute paths and empty components.
- [x] Apply excludes:
  - Defaults are `.DS_Store`, `._*` and `Thumbs.db`.
  - `--exclude` is repeatable. A pattern matches the base name, or the full
    archive path if it contains `/`.
  - `--no-default-excludes` turns off the defaults.
- [x] Skip symlinks with one warning each, unless `--follow-symlinks` is set.
      When following, detect directory cycles by `(st_dev, st_ino)` and fail
      with exit 2.
- [x] Skip sockets, FIFOs and device files with a warning.
- [x] Store empty folders as directory entries.
- [x] Detect collisions and fail with exit 2, listing every colliding
      archive path and its sources. Also compare the NFC, `casefold()` form,
      so an archive that would collide when extracted on macOS or Windows is
      caught.
- [x] Skip the output name, existing part names and `.partial` files when
      the output sits inside an input (see the decisions table).
- [x] Clamp timestamps per the decisions table. Test 2038-01-20 and
      2107-12-31 explicitly.
- [x] Implement `--dry-run` listing of the collected entries. Part grouping
      is added in Phase 4.
- [x] Tests:
  - Nested trees and mixed file and folder inputs.
  - Excludes and their defaults.
  - Symlink skip and follow, plus a symlink cycle.
  - Collisions, including case-only collisions and `ß`/`SS`.
  - Unicode names in NFC and NFD forms. Archive paths are normalized to NFC.
  - Empty files and folders, an output inside an input, and undecodable
    names on Linux.

### Phase 3: Single archive

- [ ] In `write.py`, stream the entries through `stream_zip` with the
      password, `extended_timestamps=False`, and `get_compressobj` returning
      `zlib.compressobj(level, zlib.DEFLATED, -15, 8)`:
  - Files use `ZIP_32`, or `ZIP_64` under the rules in `SPEC.md` §6.2
    (size, offset, the 65,535th entry, central-directory size). Never
    `ZIP_AUTO` (finding 3).
  - Directories use `NO_COMPRESSION_32(0, 0)`, or `NO_COMPRESSION_64(0, 0)`
    under the same rules, with a trailing `/` in the name. Budget their real
    framing in `local_bound` and `central`.
  - Mode bits are `S_IFREG | (st_mode & 0o777)` for files and
    `S_IFDIR | 0o755` for folders.
- [ ] Open each source per `SPEC.md` §6.5. Walk `relparts` from the root
      descriptor with `os.open(..., dir_fd=…)`, using `O_NOFOLLOW` under the
      default policy. `fstat` each directory against `chain` before opening
      the next component. Open the leaf with `O_NONBLOCK`, `fstat` it, and
      check it is a regular file with the recorded identity before reading.
      Then clear `O_NONBLOCK`. A mismatch raises `WriteError` (exit 3) naming
      the file.
- [ ] Hash each file with SHA-256 and count its bytes while it is read, by
      wrapping the chunk iterator. Keep the hashes in memory for `verify.py`.
- [ ] If the byte count differs from `FileEntry.size`, raise `WriteError`
      (exit 3) with a message that names the file. Read at most `size + 1`
      bytes so a growing file cannot run on.
- [ ] Open output with
      `os.open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)` under
      the `.partial` name. Call `fsync` before closing.
- [ ] In `verify.py`, stream the part through `stream_unzip` with the
      password as UTF-8 bytes and
      `allowed_encryption_mechanisms` limited to AE-2 AES-256. Drain every
      entry so the HMAC is checked. Compare the SHA-256 of each entry with
      the recorded hash. Check that the set of archive paths equals the
      planned set.
- [ ] Write `zipcheck.py` per `SPEC.md` §6.6. The writer records name,
      method, flags, both sizes, CRC field, AES extra, Zip64 extra and
      local-header offset per entry. `zipcheck` parses the EOCD and any
      Zip64 end record and locator, checks counts and directory bounds, then
      compares every central entry field with the record.
- [ ] Add the run-wide cleanup scope now, in `output.py`. It tracks every
      `.partial` this run creates and deletes them on any exception or
      Ctrl-C. Phase 4 extends it to many parts.
- [ ] Publish the final name with the no-clobber flow in `SPEC.md` §6.5:
      `os.link(partial, final)`, then remove the `.partial`. Check hard-link
      support in the output folder before writing anything.
- [ ] Tests:
  - A round trip extracts files identical to the inputs. Archive bytes are
    never compared across runs, because AES salts are random.
  - A non-ASCII password round-trips through `stream-zip` and
    `stream-unzip`.
  - A ZipCrypto archive fails verification.
  - A file that grows between collect and write fails with exit 3 and leaves
    no `.partial`.
  - A symlink planted at the `.partial` path is not written through.
  - A regular file replaced by a same-size symlink, or a parent folder
    swapped for another, between collect and write fails with exit 3.
  - A file created at the final name after the existing-output check is not
    overwritten, and the run fails with exit 3.
  - Mutation tests, each of which must fail verification: truncate the end
    record; overwrite the central directory with junk; change one central
    entry's compressed size, uncompressed size, CRC, method, flags, AES
    extra, or local-header offset; make the EOCD entry count disagree with
    the Zip64 record; point the central directory offset past the file.
  - `zipfile` accepts every unmutated part, as an independent cross-check.
  - A file replaced by a FIFO fails with exit 3 within a 5-second timeout.
  - A parent folder swapped for one that holds a hard link to the original
    file fails, because the folder's identity changed.
  - Under `--follow-symlinks`, a symlinked input root and a symlinked
    intermediate folder both archive correctly. Under the default policy,
    both are skipped with a warning.
  - The deflate bound holds at every level 0–9, for incompressible and
    empty input, at sizes around 16 KiB and 64 KiB multiples, and with
    feed sizes from 1 byte to 1 MiB (a `hypothesis` test).
  - A wrong password fails with exit 3.
  - A corrupted byte in the ciphertext fails verification.
  - The output mode is `0600`.
  - An existing output without `--force` fails with exit 3.
- [ ] Manual check: the archive opens in Keka and in Finder (Archive Utility)
      on macOS 26. Record the result in the Phase 3 commit message.

### Phase 4: Split

The admission rule is in `SPEC.md` §6.2. It needs the exact size of the
local parts already written (`written_local`). Two ways to get it:

- **A. Count compressed bytes.** Wrap the object returned by
  `get_compressobj` so it counts the bytes from `compress()` and `flush()`.
  AES-CTR does not change length. An entry's exact local size is its local
  header (including UT, AES and any Zip64 extras), plus 28 bytes of AES
  overhead, plus the compressed bytes, plus its data descriptor. This works
  only because the method is `ZIP_32`/`ZIP_64`, never `ZIP_AUTO`. This is
  the preferred design.
- **B. Count emitted bytes with a margin.** Use the bytes `stream_zip` has
  yielded so far, plus one `chunk_size` for output it may still hold. This
  works whatever the library's internals are, but wastes up to one
  `chunk_size` per part. Lower `chunk_size` to 16 KiB to limit the waste.

- [ ] Implement design A. Add a test that fails if `stream-zip` stops calling
      the wrapper's `compress` and `flush`, or if the computed local size of
      a member differs from the measured one. Fall back to design B if that
      test cannot be made to pass, and record why in
      `dev-docs/investigations/`.
- [ ] Implement `local_bound(e)` and `central(e)` in `plan.py` from
      `stream-zip`'s own header structs, for the method the writer will
      choose. Use Zip32 sizes for `ZIP_32` entries and Zip64 sizes for
      `ZIP_64` entries. Use `deflate_bound` from `SPEC.md` §6.2. Always
      reserve 98 bytes of end records.
- [ ] Before writing anything, fail with exit 2 if any single entry cannot
      fit in an empty part, using the full admission total from `SPEC.md`
      §6.4. That total includes the manifest under `--manifest`, and the
      outer layer under `--hide-names` once Phase 6 adds it. Name the file,
      and suggest the 7-Zip spanned command from `SPEC.md` §2.
- [ ] Implement admission and part rollover for `--order path`. The member
      iterator decides, before yielding each entry, whether it fits. If it
      does not, the iterator ends the current `stream_zip` call and the
      writer opens the next part.
- [ ] Name parts `bundle-partNN.zip.partial` while writing. Keep every part
      under its `.partial` name until all parts verify. Then rename them in
      order to `bundle-partNN-of-MM.zip`, or to the plain name if there is
      one part.
- [ ] Record the chosen design (A or B) and the measured slack in
      `dev-docs/investigations/`. Fold only real rule changes into `SPEC.md`
      §6.2.
- [ ] Verify that each part opens without the others, that its size on disk
      is at most `--max-size`, and that the union of paths across parts
      equals the planned set with no duplicates.
- [ ] Implement `--order size` as first-fit-decreasing on
      `local_bound + central`. Parts are assigned before writing and are
      never re-split (`SPEC.md` §6.3). They are still written one at a time.
- [ ] Extend `--dry-run` to show the planned parts as "at most N parts".
- [ ] Tests:
  - Random incompressible data with caps of 1 MB, 5 MB and 25 MB never
    produces a part over the cap.
  - A `hypothesis` property test: for random file-size lists, random name
    lengths and random caps, every part is at most the cap and every file
    lands in exactly one part. Bound the strategy to at most 200 files of at
    most 256 KiB, names of at most 200 bytes, and caps from 4 KiB to 4 MiB.
    Multi-gigabyte cases stay in the slow suite.
  - Many small files (5,000 empty files with a 1 MB cap) never exceed the
    cap. This is the central-directory case.
  - 65,535 and 65,536 entries in one part all write, verify, and open in
    `zipfile`, for files only, directories only, and a mix. Mark these
    slow.
  - Highly compressible data fills parts well. A smoke test checks that a
    part is at least 50% full when more files remain.
  - Each part extracts alone.
  - An oversized file fails with exit 2 and writes nothing.
  - Both orders are deterministic across two runs.

### Phase 5: Safe writes and failure handling

- [ ] Harden the cleanup scope from Phase 3 to cover publication. Without
      `--force`, a failure part-way removes the final names this run
      published and the remaining `.partial` files. With `--force`, it also
      renames every backup back to its original name. Backups are deleted
      only after every part is published. Publishing the last part is the
      commit point. A failed backup deletion after that keeps the new
      outputs and remaining backups, warns, and exits 0.
- [ ] Before the first byte is written, check that the output directory
      exists and is writable. Report a full disk (`ENOSPC`) clearly as exit 3.
- [ ] Implement `--force` with the backup flow in `SPEC.md` §6.5, and the
      existing-output warning from the decisions table.
- [ ] Implement `--no-verify`, which skips verification but still checks
      sizes against the cap. The generated password still prints, per the
      decisions table.
- [ ] Tests:
  - A failure injected mid-part leaves no `.partial` files and no final
    files.
  - A failure injected in verification leaves no `.partial` files.
  - A simulated Ctrl-C exits with 130 and leaves no `.partial` files.
  - `--force` overwrites only its own targets.
  - With `--force`, a failure on the second publication leaves the original
    outputs byte-identical and removes the backups and new files.
  - With `--force`, a failure on the second backup deletion keeps every new
    output, keeps the remaining backup, warns, and exits 0.

### Phase 6: Hide names

- [ ] Write each part as an inner `stream_zip` with no password and the
      chosen level. Feed its chunks as the content of one outer entry named
      `payload.zip`, with mtime 1980-01-01. Use method `ZIP_32`, or `ZIP_64`
      if the worst-case part could pass 4 GiB. Pass a level-0
      `get_compressobj` and the password on the outer call.
- [ ] Disable extended timestamps on the outer call, so the outer entry
      carries no real time.
- [ ] Reserve the outer layer in admission (`SPEC.md` §6.7). Admit an
      entry only if `deflate_bound(inner_worst) + outer_fixed ≤ max_size`,
      where `inner_worst` is the inner zip's written local bytes plus the
      next entry's local bound, all reserved central entries, and its end
      records. Compute `outer_fixed` from the same structs as Phase 4.
- [ ] Extend the structural check to the inner zip. Keep the inner stream's
      last `sum(central) + 98` bytes in a buffer and run `zipcheck` over
      them.
- [ ] Include the outer layer in the Phase 4 empty-part pre-check.
- [ ] Verify both layers. Decrypt the outer entry, stream it into
      `stream_unzip` without a password, and check the inner SHA-256 values.
- [ ] Tests:
  - Listing a part shows only `payload.zip`. Use `stream-unzip` for this,
    and also `7zz l` when it is installed.
  - The inner round trip extracts files identical to the inputs.
  - A part filled with incompressible data close to the cap stays under the
    cap after the outer layer is added, for caps exactly at and one byte
    around the admission threshold.
  - An empty inner zip (a run of empty folders only) writes and verifies.
  - A corrupt inner central directory fails verification.
  - No part exceeds the cap.
  - No temp files appear in the output directory or `$TMPDIR` during the run.

### Phase 7: Polish and release

- [ ] Implement `--manifest`. It adds `MANIFEST.txt` inside each part,
      listing every archive path and its part number. With `--manifest`,
      parts are assigned from bounds before writing and never re-split
      (`SPEC.md` §6.3). Its size is fixed before packing by the zero-padding
      rule in the decisions table. Reserve its bound in each part's budget. With `--hide-names`, the manifest goes
      inside the inner zip, never the outer one.
- [ ] Manifest tests: entry counts that cross a digit width (9→10, 99→100),
      Unicode names, a name that collides with `MANIFEST.txt` after
      casefolding, and a manifest too large to fit with any entry.
- [ ] Print progress on stderr only when stderr is a TTY. Print one final
      summary line listing the parts and their sizes.
- [ ] Write `user-docs/`: quick start, CLI reference, opening archives on
      each OS, and security notes from `SPEC.md` §7. Expand the root
      `README.md` with install and quick-start steps.
- [ ] Run the slow tests: a file over 4 GiB (Zip64) and 10,000 small files.
- [ ] Run the `7zz` interop tests (`brew install sevenzip`). `7zz t` must
      accept every part.
- [ ] Manual checks: split output opens in Keka and in Finder, and on
      Windows with 7-Zip if a machine is available. Record the results.
- [ ] Set the version to `0.1.0`. Move the `CHANGELOG.md` entries to
      `[0.1.0]` and tag `v0.1.0`.
- [ ] Run the completion steps in `dev-docs/README.md`.

## Review log

- 2026-10-08, Grok 4.7 (Cursor). Found 5 high, 9 medium and 5 low issues.
  All were applied to this plan and `SPEC.md` the same day. The highest
  were the missing central-directory reservation in admission, `ZIP_AUTO`
  ignoring the compressor and not checking sizes, the outer-layer overhead
  under `--hide-names`, and renaming parts before all of them verified.
- 2026-10-08, GPT-6.1-Sol low (Codex). Found 4 high and 5 medium issues,
  all applied the same day: deflate bound, outer-layer bound, no-clobber
  publication with `--force` backups, source identity checks, Zip64 entry
  count, structural verification, the 2038 timestamp limit, `getpass` echo
  fallback, and manifest sizing. Three were confirmed by test.
- 2026-10-08, re-review of all fixes. GPT-6.1-Sol low found 1 high, 5
  medium and 2 low issues. Muse Spark 1.3 (free, OpenCode) found 2 medium
  and 3 low. All were applied: a commit point for `--force` backups, 64-bit
  methods for directories, full central-entry comparison, two traversal
  policies, `O_NONBLOCK` leaf opens, directory identity checks, the
  empty-part pre-check including manifest and outer costs, and wording
  fixes.
- 2026-10-08, StepFun 3.7 Flash (free, via Kilo). The review did not run,
  because the free tier returned a balance error twice.

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

All three were decided on 2026-10-08 by adopting the recommendations. They
are recorded in `SPEC.md` §9.

- [x] A file over the cap stays an error with a 7-Zip hint.
- [x] No `--legacy-zipcrypto` in v1.
- [x] The manifest lives inside the parts only.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Exact counting (design A) disagrees with real output | med | high | A test compares computed and measured local sizes. Design B is the fallback. The property test gates both. |
| Hard links are unsupported on the output filesystem (some network or FAT volumes) | low | med | Check before writing and fail with a clear message. A later fallback could use `renameat2`/`renamex_np` no-replace flags. |
| A `stream-zip` 0.0.x release changes internals that design A relies on | med | med | Pin `<0.1`, commit `uv.lock`, and keep a test that fails loudly if the compressobj contract changes. |
| Finder or Archive Utility fails on Zip64 or split parts | low | med | Manual check in Phases 3 and 7. Document the fallback to Keka or `tar -xf`. |
| The password leaks through a traceback | low | high | One top-level handler prints sanitized messages. Tests assert that the password never appears in output. |
| Non-ASCII passwords differ between tools | med | low | Warn. Generated passwords are ASCII-only. Add a `7zz` test with a non-ASCII password. |
| Text-heavy inputs leave parts half-empty because the bound is loose | med | low | Accepted for v1. `--tight` is in `TODO.md` "Later". |

## Completion steps

Follow the lifecycle in [`dev-docs/README.md`](../README.md#completion-steps).
