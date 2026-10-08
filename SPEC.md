# zipseal — plan and design specification

Status: implemented on branch `feat/v1`, 2026-10-08. Drafted 2026-10-07.
Last reviewed: 2026-10-08

`zipseal` is a CLI that takes files and folders and writes them into one
password-protected zip, or into several zips that each stay under a size cap.

## 1. Goals and non-goals

Goals:

- Accept any mix of file and folder paths.
- Encrypt with AES-256. Never default to the broken legacy ZipCrypto scheme.
- Optionally split output into several zips, each no larger than `--max-size`.
- Make each part **self-contained**. A recipient can open part 2 without part 1.
  This is the main thing existing tools do not do (see §2).
- Verify every archive after writing it, by decrypting it and checking CRCs.
- Keep passwords out of shell history and the process list.
- Optionally hide file names with `--hide-names` (see §6.7).

Non-goals for v1:

- A GUI.
- Extracting archives. Recipients use 7-Zip, Keka, or similar.
- Splitting a single file across parts. A file larger than `--max-size` is an
  error in v1 (see §6.4).

## 2. Existing tools

| Tool | AES-256 | Size cap | Parts independent? | Notes |
|---|---|---|---|---|
| 7-Zip (`7zz`, `brew install sevenzip`) | Yes | Yes, `-v25m` | **No.** It writes one archive spanned across `.001`, `.002`… All parts are needed. | `7zz a -tzip -mem=AES256 -p -v25m out.zip dir/` gives AES zip volumes. `-t7z -mhe=on` also hides file names, but recipients need 7-Zip. |
| Info-ZIP `zip` (ships with macOS) | **No.** It only does ZipCrypto. | Yes, `-s 25m` | No. It writes a spanned `.z01`/`.zip` set. | ZipCrypto falls to known-plaintext attacks (for example `bkcrack`). Avoid it for sensitive data. |
| Info-ZIP `zipsplit` | No encryption of its own | Yes | Yes | It splits an *existing* zip. It does not create encrypted ones. |
| Keka (macOS GUI) | Yes | Yes | No (spanned) | Fine for one-off manual use. |

If the recipient can reassemble spanned volumes, the 7-Zip one-liner is enough
and this tool is unnecessary. The tool is worth building when each part must
stand alone. Email attachment limits and upload caps are the usual reasons.

## 3. Libraries

| Library | Role | Assessment |
|---|---|---|
| [`stream-zip`](https://pypi.org/project/stream-zip/) | Writing | **Recommended.** It writes WinZip AE-2 AES-256 and supports Zip64. It is maintained by the UK Department for Business and Trade. It yields output as byte chunks, so the tool can count exactly how many bytes each part holds. |
| [`stream-unzip`](https://pypi.org/project/stream-unzip/) | Verification | Recommended. Same maintainers. It decrypts AES entries and checks CRCs while streaming. |
| [`pyzipper`](https://pypi.org/project/pyzipper/) | Read + write | Fallback. It has a familiar `zipfile`-style API and AES 128/192/256. Its last release was 0.3.6 in July 2022, so it is effectively unmaintained. |
| `pyminizip` | Write | Not recommended. It is a C extension with a narrow API. |
| `7zz` subprocess | Optional backend | Useful later for a spanned-volume mode or a 7z mode with hidden names. |

Other languages have equivalents if Python is a poor fit. Go has
`github.com/yeka/zip`. Rust has the `zip` crate, which supports AES writes.
Python is recommended here because the repo's other tools
(`excel-pii-phi/tools/`) are Python and `uv` is installed.

## 4. CLI

```
zipseal [OPTIONS] PATH [PATH ...] -o OUTPUT
```

| Option | Default | Meaning |
|---|---|---|
| `-o, --output PATH` | required | Output name, such as `bundle.zip`. Parts become `bundle-part01-of-03.zip`. |
| `--max-size SIZE` | none (one zip) | Cap per part. Accepts raw bytes, decimal suffixes `KB`/`MB`/`GB`/`TB` (and bare `K`/`M`/`G`/`T`), or binary suffixes `KiB`/`MiB`/`GiB`/`TiB`. Suffixes are case-insensitive. Anything else is a usage error. |
| `--password-prompt` | default | Prompt twice with `getpass` and require a match. If `getpass` cannot turn off echo, it would fall back to visible input. That warning (`GetPassWarning`) is treated as an error, and the run stops before reading anything. |
| `--password-env VAR` | — | Read the password from an environment variable. |
| `--password-file PATH` | — | Read the first line of a file. Warn if the file is group- or world-readable. |
| `--generate-password` | off | Make a random password with `secrets` (default 24 characters) and print it once to stderr. |
| `--level 0-9` | 6 | Deflate level. `0` stores without compression. |
| `--exclude GLOB` | `.DS_Store`, `._*`, `Thumbs.db` | Repeatable. `--no-default-excludes` turns off the defaults. |
| `--follow-symlinks` | off | By default, symlinks are skipped with a warning. |
| `--order {path,size}` | `path` | `path` keeps related files together. `size` packs largest-first for fewer parts. |
| `--hide-names` | off | Nest each part's real zip inside an encrypted outer zip, so names are unreadable without the password (see §6.7). |
| `--manifest` | off | Add `MANIFEST.txt` inside each part. It lists every file and which part holds it. Part numbers are zero-padded to the width of the largest possible part count (the number of entries), so the manifest's size is known before packing and is the same in every part. |
| `--no-verify` | verify on | Skip the post-write decrypt check. |
| `--force` | off | Overwrite existing output files. |
| `--dry-run` | off | Print the planned parts and their contents. Write nothing. |

There is deliberately no `--password VALUE` flag. A value on the command line
lands in shell history and is visible to other users through `ps`.

Exit codes: `0` success, `1` usage error, `2` input error (missing path,
oversized file), `3` write or verify failure.

## 5. Architecture

The built modules add `sources.py` (safe source reads), `zipcheck.py`
(structural verification), `output.py` (naming and publication),
`pipeline.py` (orchestration) and `passwords.py`. The original sketch:

```
cli.py        argument parsing, password acquisition, exit codes
collect.py    walk inputs → ordered list of FileEntry(src, arcname, size, mtime, mode)
plan.py       size bound per entry; assigns entries to parts
write.py      streams one part through stream-zip, counting bytes
verify.py     re-reads each part with stream-unzip and checks names + CRCs
```

Packaging: a `pyproject.toml` with a `zipseal` console script. Run it with
`uv run zipseal …` or install it with `uv tool install .`.

## 6. Key design decisions

### 6.1 Archive paths

- A folder input `~/data/reports` stores entries as `reports/…`. The top-level
  folder name is kept, which matches `zip -r` and Finder.
- A file input is stored at the archive root under its base name.
- Two inputs that map to the same archive path are an error. The tool lists
  the collisions. It never silently renames or overwrites.
- Archive paths always use `/` and never contain `..` or a leading `/`.
- Empty folders are stored as directory entries.

### 6.2 Staying under the size cap

The compressed size of a file is not known until it has been compressed. The
tool therefore uses a worst-case bound when it decides where a file goes, and
it counts the real bytes once the file is written.

Each entry is written with an explicit method. Files use `ZIP_32` and
directories use `NO_COMPRESSION_32(0, 0)`, unless one of these holds. Then
files use `ZIP_64` and directories use `NO_COMPRESSION_64(0, 0)`:

- the entry's bound, or the part's running offset plus that bound, could
  pass `0xFFFFFFFF`;
- the entry is the part's 65,535th entry or later. With explicit `ZIP_32`,
  `stream-zip` fails at 65,536 entries, whether they are files or
  directories. Switching later entries to a 64-bit method makes it write
  Zip64 end records instead (tested 2026-10-08);
- the reserved central directory could pass `0xFFFFFFFF` bytes.

`ZIP_AUTO` is not used, because it ignores the caller's compressor and does
not check the size it is given.

The compressor is fixed: raw deflate (`wbits=-15`), `memLevel=8`, at the
chosen level. For that configuration zlib guarantees this bound on the
compressed size of `n` input bytes, at every level including 0:

```
deflate_bound(n) = n + (n >> 12) + (n >> 14) + (n >> 25) + 7
```

Extended timestamps are disabled (`extended_timestamps=False`). `stream-zip`
packs them as signed 32-bit seconds, which fails after January 2038. Entries
carry DOS timestamps only, which cover 1980 to 2107 in local time at 2-second
resolution.

Each entry has two parts to its cost. The local part is written as the entry
streams. The central part is written only when the part closes:

```
local_bound(e) = local_header(e)         # 30 + len(name) + AES extra (11)
                                         #   + Zip64 extra (20) if ZIP_64
               + aes_overhead            # 16 salt + 2 verifier + 10 MAC
               + deflate_bound(e.size)
               + data_descriptor(e)      # 16, or 24 if ZIP_64
central(e)     = 46 + len(name) + extra fields   # AES, and Zip64 if needed
end_records    = 98                      # Zip64 end record + locator + EOCD
```

The writer admits the next entry into the current part only if

```
written_local + local_bound(next)
  + sum(central(e) for every admitted entry, plus next)
  + end_records  ≤  max_size
```

`written_local` is the exact byte count of the local parts already written.
The central entries of every admitted entry are reserved, because none of
them has been written yet. The end records are always reserved at their
Zip64 size, which wastes at most 76 bytes but covers parts with more than
65,535 entries. If the entry does not fit, the writer closes the part and
starts a new one.

This guarantees no part ever exceeds the cap. The only slack is the gap
between each file's bound and its real size. Already-compressed inputs
(JPEG, MP4, other zips) have almost no gap. Text can leave a part partly
unfilled. That is acceptable for v1. A later `--tight` mode could compress
each file to a temporary file first and use its exact size.

Under `--order path` without `--manifest`, part boundaries depend on real
compressed sizes, so the part count is only known at the end. In the
upfront-assignment modes of §6.3, the part count is known before writing.
Either way the writer uses temporary names and renames the parts to
`-partNN-of-MM.zip` only after every part verifies (§6.5).

### 6.3 Ordering

`--order path` (the default) sorts by archive path. Files from one folder
therefore end up in the same or adjacent parts. `--order size` uses
first-fit-decreasing and usually produces fewer parts, but it scatters
related files. Both orders are deterministic, so the same input gives the
same split.

`--order path` assigns parts while streaming. Each decision uses the exact
bytes written so far plus worst-case bounds for the next entry, per the
§6.2 rule.
`--order size` and `--manifest` instead assign every entry to a part from
bounds alone, before anything is written, and never re-split. First-fit
needs to see all parts at once, and a manifest must list every part before
part 1 is written. Packing is looser in those modes.

### 6.4 Files larger than the cap

In v1, the run stops before anything is written if any single entry cannot
fit in an empty part. "Fit" uses the full §6.2 admission total for that
entry alone in a new part. Under `--manifest` that total includes the
manifest's bound. Under `--hide-names` it includes the outer layer from §6.7.
So admission can never fail on an empty part. The error names the file and suggests the 7-Zip spanned
command from §2. A later version could add `--oversize=volumes`, which
delegates that file to `7zz -v`.

### 6.5 Safe writes

- Each part is written under a `.partial` name. No part is renamed until
  every part has been written and verified. Then all parts are renamed, in
  order. A failure therefore never leaves a final-named part behind.
- On any failure, all `.partial` files from the run are deleted.
- `.partial` files are opened with `O_CREAT | O_EXCL | O_NOFOLLOW`, so a
  planted file or symlink is never written through.
- A source that changes between collection and reading stops the run.
  Collection records the device, inode and type of every file and of every
  directory on the path to it, plus each file's size. Reading starts from a
  directory descriptor held since collection. It opens the path one
  component at a time and `fstat`s each one against the record before going
  further. The leaf is opened with `O_NONBLOCK`, so a file swapped for a FIFO
  is rejected by type instead of blocking the open. The writer also counts
  the bytes it reads. A swapped file or folder, a file replaced by a symlink
  or FIFO, or a size change all fail.
- Traversal has two policies. By default every component, including the
  input root, is opened with `O_NOFOLLOW`. With `--follow-symlinks`,
  components are opened without `O_NOFOLLOW`, so symlinks resolve. The
  identity of what they resolve to is still checked against the record.
- Final names are published without clobbering. Each `.partial` is
  hard-linked to its final name with `os.link`, which fails if the name
  exists, and then the `.partial` is removed. A file that appears at a final
  name during the run is therefore never overwritten. If the filesystem does
  not support hard links, the run fails with exit 3 before writing.
- With `--force`, each existing final name is first renamed to a private
  backup name in the same folder. Then the new part is published. If any
  step fails before every part is published, the run removes what it
  published and restores every backup, so the previous outputs survive.
- Publishing the last part is the commit point. After it, nothing is rolled
  back. The run then deletes the backups. If a deletion fails, the run keeps
  the new outputs and any remaining backups, prints a warning naming the
  leftover backups, and still exits 0.
- Output files are created with mode `0600`.

### 6.6 Verification

After all parts are written, `verify.py` reopens each one with the password.
It allows only AE-2 AES-256 entries, so a ZipCrypto or AE-1 entry fails.
AE-2 stores a CRC of zero, so integrity comes from the AES HMAC, which
`stream-unzip` checks as it decrypts. Verification also compares the
SHA-256 of each decrypted entry with a SHA-256 taken while the source was
read. It confirms the
set of archive paths across all parts equals the planned set. It also checks
that each part's size on disk is at most `--max-size`.

`stream-unzip` reads only the local entries. It stops at the first
central-directory signature and ignores everything after it, so an archive
with a corrupt central directory or end record would still pass. Verification
therefore also checks the structure itself, with its own small parser in
`zipcheck.py`. The parser reads the end of central directory record, and the
Zip64 end record and locator when present. It checks that their entry counts
agree, and that the central directory ends exactly where the end records
begin. It then parses every central entry and checks it against the file
itself. The local header at the recorded offset must have the same name,
flags, method and AES field. The data descriptor after the data must have
the same CRC and sizes. Entries must be contiguous, from offset 0 to the
start of the central directory. Every entry must be AE-2 AES-256 with a zero
CRC. Finally, the list of names and uncompressed sizes must equal what the
writer recorded. Any difference fails verification. Checking the central
directory against the bytes on disk catches the same corruption as
predicting every field, without duplicating stream-zip's layout logic.

The standard library's `zipfile` is not enough on its own. It accepts a
central entry whose sizes or CRC were changed. Tests still use it as an
independent cross-check.

Under `--hide-names` the inner zip is checked the same way. Verification
keeps the inner stream's trailing bytes, which hold its central directory
and end records, and runs the same parser over them.

### 6.7 Hiding file names (`--hide-names`)

Zip encrypts file contents but stores names, sizes and timestamps in
plaintext headers. Anyone can list them without the password. `--hide-names`
fixes this by nesting:

```
bundle-part01-of-03.zip          outer: AES-256, deflate level 0
└── payload.zip                  one entry with a fixed, generic name
    ├── reports/q3.xlsx          inner: deflate, no encryption
    └── reports/notes.txt
```

- **The inner zip is not encrypted.** The outer AES layer already protects
  it. A second password, or the same password twice, adds no real security.
  It would only make the recipient type a password twice.
- **The outer zip uses deflate level 0.** The inner zip is already
  compressed, so compressing again wastes time. A truly stored entry is not
  possible, because `stream-zip` needs a stored entry's size and CRC before
  it starts, and the inner zip is still being generated. Level 0 emits
  stored deflate blocks instead and needs neither value. The outer entry
  uses `ZIP_32`, or `ZIP_64` if the worst-case part could pass 4 GiB.
- **The outer entry hides its metadata.** Its name is always `payload.zip`.
  Its timestamp is fixed at 1980-01-01, so it does not reveal when the files
  were made.
- **No plaintext touches disk.** `stream-zip` yields the inner zip as chunks.
  Those chunks feed straight in as the content of the outer entry, so no
  temporary unencrypted file is written.
- **Splitting still works.** Each part gets its own inner zip that holds only
  that part's files. Every part still opens on its own. The size rule in
  §6.2 must reserve the outer layer. The inner zip's worst-case size is its
  local bounds plus its central entries plus its end records. The outer entry
  then costs `deflate_bound(inner)` plus the outer local header, AES
  overhead, data descriptor, central entry and end records. Level 0 does not
  always fill 65,535-byte blocks, so a fixed per-block figure is not safe.
  1,000,000 bytes fed in 64 KiB chunks produced 115 bytes of expansion, not
  80.
- **Verification checks both layers.** It decrypts the outer zip, opens the
  inner zip from the stream, and checks every inner SHA-256. Inner entries
  are not encrypted, so their CRCs are checked too.

An outside observer still sees each part's total size, the part count, and
the file's own timestamp on disk. Nothing else leaks.

Recipients extract twice. They open the outer zip with the password, then
open `payload.zip`, which needs no password.

The alternative is 7z format with `7zz -mhe=on`, which encrypts names
natively. It is cleaner, but it needs a 7-Zip binary for writing and
reading. macOS can open AES zips natively but not 7z files, so 7z puts more
burden on Mac recipients. It remains a reasonable later `--format 7z` backend. Nesting is the v1 choice because it
keeps the tool pure Python. Renaming files to random IDs was rejected. It
breaks the result for the recipient unless they also run a restore step.

### 6.8 Other behavior

- **Part names.** A run that produces one part writes exactly the `-o`
  name, even with `--max-size`. Two or more parts are named
  `NAME-partNN-of-MM.zip`, with three digits when there are more than 99.
- **Existing outputs.** Before writing, the run fails with exit 3 if the
  `-o` name exists, or any file named `NAME-part` + digits + `-of-` +
  digits + `.zip`. `--force` lifts this, and replaces only the names this run
  produces (§6.5). Other old parts are listed in a warning, never deleted.
- **Output inside an input.** The walker skips the output name, any
  existing part name for it, and `.partial` files.
- **Dry run.** `--dry-run` needs no password. It plans from worst-case
  bounds, so it reports "at most N parts".
- **Timestamps.** DOS timestamps in local time are clamped to 1980-01-01
  00:00:00 through 2107-12-31 23:59:58, with one warning per clamped file.
- **File names.** Names that do not decode as UTF-8 stop the run with exit 2.
  Archive paths are normalized to NFC. Two paths that are equal after
  `str.casefold()` are a collision, because they would clash when extracted
  on macOS or Windows.
- **Manifest collision.** If an input already maps to `MANIFEST.txt` at the
  archive root, `--manifest` fails with exit 2.
- **Interrupt.** Ctrl-C removes this run's `.partial` files and exits 130.
- **Generated password.** `--generate-password` prints the password once,
  to stderr, after every part has verified (or passed the size check under
  `--no-verify`) and just before publication. A run that fails earlier
  prints no password. If publication then fails and rolls back, the run
  says that no archive was written.
- **Password handling.** Passwords are encoded as UTF-8, as 7-Zip and
  libarchive expect. `stream-zip` hands a `str` password to pycryptodome,
  which encodes it as Latin-1, so zipseal passes the UTF-8 bytes decoded as
  Latin-1. Without that, non-ASCII passwords would not open elsewhere. Generated passwords
  use only ASCII letters and digits. A non-ASCII password, or one shorter
  than 12 characters, prints a warning. An empty password is an error.

## 7. Security notes for the README

- AES-256 (WinZip AE-2) protects file contents. It does **not** hide file
  names, sizes, or timestamps unless you use `--hide-names` (§6.7).
- macOS support for AES zips depends on the tool. Tested on macOS 26.6.2:
  `tar -xf x.zip --passphrase …` (libarchive) extracts AES-256 zips.
  `ditto -x -k` fails with "Unknown compression type", and `/usr/bin/unzip`
  fails with "unsupported compression method 99". Double-clicking in Finder
  (Archive Utility) prompts for the password and extracts the zip. That was
  confirmed manually on 2026-10-08. Releases before macOS 11 do not support
  AES zips.
- Windows Explorer support for AES zips is unreliable, so recommend 7-Zip on
  Windows.
- Strength depends on the password. AE-2 derives keys with
  PBKDF2-HMAC-SHA1 at only 1,000 iterations, so a weak password falls quickly
  to offline guessing. Recommend `--generate-password`, and send the password
  through a different channel than the zip.
- `--password-env` keeps the value off the command line. Other processes of
  the same user can still read a process's environment, so prefer the prompt
  or a `0600` password file on shared machines.
- Python cannot reliably wipe a password from memory. It lives for the run.
- All parts share one password. That is a convenience trade-off and is fine
  with AES-256.

## 8. Implementation plan

The detailed, tracked version of this plan is
[`dev-docs/plans/2026-10-08-v1-implementation.md`](dev-docs/plans/2026-10-08-v1-implementation.md).
This section is the summary.

1. **Scaffold.** Add `pyproject.toml` with `stream-zip`, `stream-unzip` and
   `pytest`. Add the `cli.py` skeleton, password acquisition and size parsing.
2. **Collect.** Walk the inputs and apply excludes, symlink rules and
   collision detection. Implement `--dry-run` listing.
3. **Single archive.** Write one AES-256 zip with no cap. Verify it opens in
   `7zz` and Keka.
4. **Split.** Add the bound function, the admit rule and part renaming.
5. **Verify and safe writes.** Add the `.partial` → rename flow, cleanup on
   failure, and `0600` permissions.
6. **Polish.** Add the manifest, `--order size`, progress output on stderr,
   and the README.

Tests (pytest, using generated temporary files):

- A round trip of mixed files and nested folders extracts files identical to
  the inputs. The archives themselves differ on every run, because AES salts
  are random.
- Random incompressible data at caps of 1 MB, 5 MB and 25 MB never produces a
  part over the cap.
- Every part opens on its own, without the other parts.
- A wrong password fails verification.
- Archive path collisions, oversized files and existing outputs produce the
  documented exit codes.
- Unicode file names, empty files, empty folders and a file over 4 GiB
  (Zip64) all work. Mark the 4 GiB test slow.
- With `--hide-names`, `7zz l` on a part lists only `payload.zip`. The inner
  round trip also extracts identical files, and no part exceeds the cap.
- `7zz t -p…` accepts every part. Skip this test if `7zz` is not installed.

## 9. Open questions

These were decided on 2026-10-08 by adopting the plan's recommendations.
Reopen one if a real recipient needs something else.

- A single file over the cap stays an error in v1, with a 7-Zip hint (§6.4).
- There is no `--legacy-zipcrypto` in v1. ZipCrypto is broken, and no
  recipient has needed it yet.
- The manifest lives only inside the parts. A manifest beside the parts
  would leak the names that `--hide-names` hides.

## 10. References

- stream-zip, password protection (AES-256, WinZip AE-2, and its metadata
  caveats): <https://stream-zip.docs.trade.gov.uk/get-started/password-protection>
- stream-zip on PyPI: <https://pypi.org/project/stream-zip/>
- stream-unzip on PyPI: <https://pypi.org/project/stream-unzip/>
- Bandizip, Mac Finder and encrypted zips (AES support from macOS 11):
  <https://en.bandisoft.com/bandizip/help/cannot-extract-zip-with-password-on-mac/>
- pyzipper on PyPI (last release 0.3.6, 2022-07-31): <https://pypi.org/project/pyzipper/>
- 7-Zip AES-256 with header encryption (`-mhe`) and volumes (`-v`):
  <https://www.cnx-software.com/2011/02/22/aes-256-encryption-and-file-names-encryption-with-7-zip-7z/>
