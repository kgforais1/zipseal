# zipseal — plan and design specification

Status: draft, 2026-10-07. Nothing is implemented yet.

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
| `--max-size SIZE` | none (one zip) | Cap per part. Accepts `25MB`, `10MiB`, `2G`, or raw bytes. |
| `--password-prompt` | default | Prompt twice with `getpass` and require a match. |
| `--password-env VAR` | — | Read the password from an environment variable. |
| `--password-file PATH` | — | Read the first line of a file. Warn if the file is group- or world-readable. |
| `--generate-password` | off | Make a random password with `secrets` (default 24 characters) and print it once to stderr. |
| `--level 0-9` | 6 | Deflate level. `0` stores without compression. |
| `--exclude GLOB` | `.DS_Store`, `._*`, `Thumbs.db` | Repeatable. `--no-default-excludes` turns off the defaults. |
| `--follow-symlinks` | off | By default, symlinks are skipped with a warning. |
| `--order {path,size}` | `path` | `path` keeps related files together. `size` packs largest-first for fewer parts. |
| `--hide-names` | off | Nest each part's real zip inside an encrypted outer zip, so names are unreadable without the password (see §6.7). |
| `--manifest` | off | Add `MANIFEST.txt` inside each part. It lists every file and which part holds it. |
| `--no-verify` | verify on | Skip the post-write decrypt check. |
| `--force` | off | Overwrite existing output files. |
| `--dry-run` | off | Print the planned parts and their contents. Write nothing. |
| `--legacy-zipcrypto` | off | Use ZipCrypto for old unzip tools. Prints a loud warning. Needs `pyzipper`. Probably defer past v1. |

There is deliberately no `--password VALUE` flag. A value on the command line
lands in shell history and is visible to other users through `ps`.

Exit codes: `0` success, `1` usage error, `2` input error (missing path,
oversized file), `3` write or verify failure.

## 5. Architecture

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

For each entry, the bound is:

```
bound(e) = deflate_worst(e.size)   # size + 5 bytes per 16 KiB block + 64
         + local_header(e)         # 30 + len(name) + Zip64/AES extra fields
         + aes_overhead            # 16 salt + 2 verifier + 10 MAC
         + data_descriptor         # 24 with Zip64
         + central_entry(e)        # 46 + len(name) + extra fields
```

The writer admits the next entry into the current part only if
`bytes_written_so_far + bound(next) + end_of_central_dir ≤ max_size`.
Otherwise it closes the part and starts a new one.

This guarantees no part ever exceeds the cap. The only slack is the gap
between the last file's bound and its real size. Already-compressed inputs
(JPEG, MP4, other zips) have almost no gap. Text can leave a part partly
unfilled. That is acceptable for v1. A later `--tight` mode could compress
each file to a temporary file first and use its exact size.

Because part boundaries depend on real compressed sizes, the part count is
only known at the end. The writer uses temporary names and renames the parts
to `-partNN-of-MM.zip` once `MM` is known.

### 6.3 Ordering

`--order path` (the default) sorts by archive path. Files from one folder
therefore end up in the same or adjacent parts. `--order size` uses
first-fit-decreasing and usually produces fewer parts, but it scatters
related files. Both orders are deterministic, so the same input gives the
same split.

### 6.4 Files larger than the cap

In v1, any single file whose bound exceeds `--max-size` stops the run before
anything is written. The error names the file and suggests the 7-Zip spanned
command from §2. A later version could add `--oversize=volumes`, which
delegates that file to `7zz -v`.

### 6.5 Safe writes

- Each part is written as `NAME.partial` and renamed only after it verifies.
- On any failure, all `.partial` files from the run are deleted.
- Existing output files are never overwritten without `--force`.
- Output files are created with mode `0600`.

### 6.6 Verification

After all parts are written, `verify.py` reopens each one with the password.
It decrypts every entry, checks the CRC and the AES MAC, and confirms the
set of archive paths across all parts equals the planned set. It also checks
that each part's size on disk is at most `--max-size`.

### 6.7 Hiding file names (`--hide-names`)

Zip encrypts file contents but stores names, sizes and timestamps in
plaintext headers. Anyone can list them without the password. `--hide-names`
fixes this by nesting:

```
bundle-part01-of-03.zip          outer: AES-256, stored (no compression)
└── payload.zip                  one entry with a fixed, generic name
    ├── reports/q3.xlsx          inner: deflate, no encryption
    └── reports/notes.txt
```

- **The inner zip is not encrypted.** The outer AES layer already protects
  it. A second password, or the same password twice, adds no real security.
  It would only make the recipient type a password twice.
- **The outer zip stores without compression.** The inner zip is already
  compressed, so compressing again wastes time.
- **The outer entry hides its metadata.** Its name is always `payload.zip`.
  Its timestamp is fixed at 1980-01-01, so it does not reveal when the files
  were made.
- **No plaintext touches disk.** `stream-zip` yields the inner zip as chunks.
  Those chunks feed straight in as the content of the outer entry, so no
  temporary unencrypted file is written.
- **Splitting still works.** Each part gets its own inner zip that holds only
  that part's files. Every part still opens on its own. The size rule in
  §6.2 adds a fixed outer overhead (one local header, one central entry, AES
  fields and end record), about 200 bytes per part.
- **Verification checks both layers.** It decrypts the outer zip, opens the
  inner zip from the stream, and checks every inner CRC.

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
- Strength depends on the password. Recommend `--generate-password`, and
  send the password through a different channel than the zip.
- All parts share one password. That is a convenience trade-off and is fine
  with AES-256.

## 8. Implementation plan

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

- A round trip of mixed files and nested folders gives byte-identical output.
- Random incompressible data at caps of 1 MB, 5 MB and 25 MB never produces a
  part over the cap.
- Every part opens on its own, without the other parts.
- A wrong password fails verification.
- Archive path collisions, oversized files and existing outputs produce the
  documented exit codes.
- Unicode file names, empty files, empty folders and a file over 4 GiB
  (Zip64) all work. Mark the 4 GiB test slow.
- With `--hide-names`, `7zz l` on a part lists only `payload.zip`. The inner
  round trip is also byte-identical, and no part exceeds the cap.
- `7zz t -p…` accepts every part. Skip this test if `7zz` is not installed.

## 9. Open questions

- Should a single file over the cap be split with 7-Zip in v1, or stay an
  error?
- Is `--legacy-zipcrypto` needed for any real recipient?
- Should the manifest live inside each part (private) or beside the parts
  (readable without the password, but it leaks names)? The draft puts it
  inside.

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
