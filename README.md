# zipseal

Last reviewed: 2026-10-08

`zipseal` writes files and folders into AES-256 encrypted zips. It can split
the output into parts that each stay under a size cap and each open on their
own, which suits email and upload limits. It can also hide file names.

```sh
uv tool install .
zipseal reports/ -o bundle.zip --max-size 20MB --generate-password
```

- Users: start with the [quick start](user-docs/quick-start.md), then the
  [CLI reference](user-docs/cli.md) and [security notes](user-docs/security.md).
- Contributors and agents: start with [`AGENTS.md`](AGENTS.md). The design
  is in [`SPEC.md`](SPEC.md).
