# Quick start

Last reviewed: 2026-10-08

## Install

zipseal needs Python 3.11 or later and [`uv`](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/kgrizz-git/zipseal.git
cd zipseal
uv tool install .
```

This puts `zipseal` on your `PATH`. To run it without installing, use
`uv run zipseal …` inside the repository.

## Make one encrypted zip

```sh
zipseal reports/ notes.txt -o bundle.zip --generate-password
```

zipseal prints the generated password once, on stderr. Send it to the
recipient through a different channel than the zip, such as a phone call or
a separate message.

## Split into parts for email

```sh
zipseal reports/ -o bundle.zip --max-size 20MB --generate-password
```

This writes `bundle-part01-of-03.zip`, `bundle-part02-of-03.zip` and so on.
Every part is a complete zip that opens on its own, and no part is larger
than 20 MB. All parts use the same password.

## Hide the file names too

```sh
zipseal reports/ -o bundle.zip --max-size 20MB --hide-names --generate-password
```

Without `--hide-names`, anyone can list the file names, sizes and dates in a
zip without the password. With it, each part holds a single encrypted
`payload.zip`. The recipient opens the part with the password, then opens
`payload.zip`, which needs no password.

## Check before writing

```sh
zipseal reports/ -o bundle.zip --max-size 20MB --dry-run
```

`--dry-run` lists what would be archived and the most parts it could take.
It writes nothing and asks for no password.

Next: [CLI reference](cli.md), [opening the archives](opening-archives.md),
and [security notes](security.md).
