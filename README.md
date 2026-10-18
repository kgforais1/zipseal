# zipseal

![zipseal icon](assets/icon.svg)

[![CI](https://github.com/kgforais1/zipseal/actions/workflows/ci.yml/badge.svg)](https://github.com/kgforais1/zipseal/actions/workflows/ci.yml)
[![Dependency audit](https://github.com/kgforais1/zipseal/actions/workflows/dependency-audit.yml/badge.svg)](https://github.com/kgforais1/zipseal/actions/workflows/dependency-audit.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![AES-256](https://img.shields.io/badge/encryption-AES--256-2E7D32)
[![MIT license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Last reviewed: 2026-10-18

`zipseal` writes files and folders into AES-256 encrypted zips. It can split
the output into parts that each stay under a size cap, such as an email
attachment limit, and every part opens on its own. It can also hide file
names, which ordinary encrypted zips leave readable.

## Why

Existing tools cover parts of this. 7-Zip can split an AES zip, but the
pieces form one spanned archive, so the recipient needs every piece. macOS
`zip` only does ZipCrypto, which is broken. zipseal makes **independent**
AES-256 parts: send part 2 alone and it still opens.

## Features

- AES-256 (WinZip AE-2) encryption only. There is no ZipCrypto option.
- `--max-size` splits into self-contained parts that never exceed the cap.
- `--hide-names` hides file names, sizes and dates inside an encrypted
  `payload.zip`.
- `--manifest` adds a list of which part holds each file.
- Every part is decrypted and checked after writing, before it gets its
  final name. A failed run leaves nothing behind.
- Existing files are never overwritten unless you pass `--force`, and even
  then the old ones are restored if the run fails.
- The password never goes on the command line. It comes from a prompt, an
  environment variable, a file, or `--generate-password`.
- Opens in Finder (macOS 11+), 7-Zip, Keka and `bsdtar`.

## Install

zipseal needs Python 3.11 or later and [`uv`](https://docs.astral.sh/uv/).

```sh
uv tool install git+https://github.com/kgforais1/zipseal.git
```

That puts two commands on your `PATH`: `zipseal` and `zipseal-gui`. From a
clone, `scripts/install.sh` does the same as an editable install.

### Open the window without a terminal (macOS)

In a clone, double-click `zipseal-gui.command` in Finder. It opens Terminal
and then the zipseal window, with no install step. The first run gives the file
its zipseal icon. See [the zipseal window](user-docs/gui.md) for what to do if
macOS blocks a downloaded copy.

## Use

```sh
# One encrypted zip with a strong random password, printed once to stderr
zipseal reports/ notes.txt -o bundle.zip --generate-password

# Parts of at most 20 MB for email; each opens on its own
zipseal reports/ -o bundle.zip --max-size 20MB --generate-password

# Also hide the file names
zipseal reports/ -o bundle.zip --max-size 20MB --hide-names --generate-password

# See what would happen, without writing anything
zipseal reports/ -o bundle.zip --max-size 20MB --dry-run
```

Prefer a window? Run `zipseal-gui` for the same options with a file picker,
progress bar and a one-time view of the generated password.

Several parts are named `bundle-part01-of-03.zip`, `bundle-part02-of-03.zip`
and so on. Send the password through a different channel than the zip.
Run `zipseal --help` for every option.

## Opening the archives

Double-click in Finder on macOS 11 or later, or use 7-Zip, Keka or
`tar -xf FILE.zip`, which prompts for the password. macOS's `/usr/bin/unzip` cannot
open AES zips. With `--hide-names`, Finder unpacks the inner `payload.zip`
for you, while Keka and 7-Zip extract it as a second zip to open. See
[opening the archives](user-docs/opening-archives.md).

## Security in brief

AES-256 protects the contents, with the key derivation every AES zip uses, so
a zipseal archive is no weaker than one from 7-Zip or WinZip. The weak point
is the password: the zip format derives its key with PBKDF2-SHA1 at only
1,000 iterations, so short passwords can be guessed offline. Use
`--generate-password` for anything sensitive; if you must choose your own, use
16+ characters drawn from the 62 letters and digits, or five unrelated words,
letting a tool pick them rather than choosing them yourself. Without
`--hide-names`, anyone can list file names, sizes and dates. See the
[security notes](user-docs/security.md).

## Documentation

- [Quick start](user-docs/quick-start.md)
- [The zipseal window](user-docs/gui.md)
- [CLI reference](user-docs/cli.md)
- [Opening the archives](user-docs/opening-archives.md)
- [Security notes](user-docs/security.md)
- Design: [`SPEC.md`](SPEC.md)

## Development

```sh
git clone https://github.com/kgforais1/zipseal.git
cd zipseal
uv sync
pre-commit install
uv run pytest            # fast suite
uv run pytest -m slow    # Zip64, 65,536 entries, 25 MB parts
```

Contributors and AI agents start with [`AGENTS.md`](AGENTS.md).
`dev-docs/` holds plans, investigations and the doc rules.

## License

[MIT](LICENSE).
