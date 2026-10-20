# CLI reference

Last reviewed: 2026-10-08

```
zipseal [OPTIONS] PATH [PATH ...] -o OUTPUT
```

A folder is stored under its own name, so `~/data/reports` becomes
`reports/…` in the zip. A file is stored at the top level under its own name.

## Output

| Option | Meaning |
|---|---|
| `-o, --output PATH` | Output name, such as `bundle.zip`. Required. |
| `--max-size SIZE` | Cap per part. Without it, zipseal writes one zip. |
| `--order path` | Default. Keeps files from the same folder together. |
| `--order size` | Packs largest files first, which usually needs fewer parts. |
| `--hide-names` | Nest each part's files inside one encrypted `payload.zip`. |
| `--manifest` | Add `MANIFEST.txt` to every part, listing which part holds each file. |
| `--force` | Replace existing outputs. Old outputs are restored if the run fails. |
| `--dry-run` | Show what would be written. Write nothing. |

Sizes accept plain bytes, decimal units (`KB`, `MB`, `GB`, `TB`, or `K`, `M`,
`G`, `T`) and binary units (`KiB`, `MiB`, `GiB`, `TiB`). Units are not case
sensitive. `25MB` is 25,000,000 bytes, and `25MiB` is 26,214,400 bytes.

With one part, the output keeps the `-o` name exactly. With several, they are
named `NAME-volumeNN-of-MM.zip`.

## Password

Choose at most one. Without any, zipseal prompts.

| Option | Meaning |
|---|---|
| `--password-prompt` | Ask twice, with typing hidden. Refuses to run if the terminal cannot hide input. |
| `--password-env VAR` | Read the password from environment variable `VAR`. |
| `--password-file PATH` | Read the first line of a file. Warns if other users can read it. |
| `--generate-password` | Make a random 24-character password and print it once to stderr. |

There is no option that takes the password itself on the command line. That
would leave it in your shell history and visible to other users.

## What goes in

| Option | Meaning |
|---|---|
| `--exclude GLOB` | Skip matching files and folders. Repeatable. A pattern with `/` matches the archive path; otherwise it matches the name. |
| `--no-default-excludes` | Stop skipping `.DS_Store`, `._*` and `Thumbs.db`. |
| `--follow-symlinks` | Follow symlinks. By default they are skipped with a warning. |
| `--level 0-9` | Compression level. Default 6. `0` means no compression. |
| `--no-verify` | Skip decrypting each part after writing. The size cap is still checked. |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success. |
| 1 | Usage error, such as a bad option or mismatched passwords. |
| 2 | Input error, such as a missing path, a name collision, a file too large for `--max-size`, or nothing left to archive after skips and excludes. |
| 3 | Write or verify failure. Nothing is left behind. |
| 130 | Cancelled with Ctrl-C. A cancel before the parts are published leaves nothing behind. |

## Safety guarantees

- Each part is written under a temporary name ending in `.temp`, verified
  (unless `--no-verify`), and only then given its final name. On a failure,
  zipseal tries to remove every `.temp` file, and warns about any it could not
  delete. zipseal prints a notice when they appear. Do not
  rename, move or open them while it runs.
- zipseal never overwrites a file it did not expect, even one created while
  it was running.
- If an earlier run was killed and left `.temp` files, the next run stops
  before writing and lists them. Check them, then delete them. Older versions
  named these files `.partial`, and those stop a run too.
- If a source file changes or is swapped while zipseal runs, the run stops.
