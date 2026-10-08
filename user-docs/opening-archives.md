# Opening the archives

Last reviewed: 2026-10-08

zipseal writes standard WinZip AES-256 (AE-2) zips. Most modern tools open
them, but some built-in ones do not.

| Platform | Works | Does not work |
|---|---|---|
| macOS 11 and later | Double-click in Finder (Archive Utility) prompts for the password. `tar -xf FILE.zip --passphrase PASSWORD`. Keka. 7-Zip (`brew install sevenzip`). | `/usr/bin/unzip` ("unsupported compression method 99"). `ditto -x -k`. |
| Windows | 7-Zip. | File Explorer's built-in zip support is unreliable for AES. |
| Linux | 7-Zip (`7zz`), `bsdtar` (libarchive). | Info-ZIP `unzip`. |

Each part opens on its own. You do not need the other parts.

## Parts made with `--hide-names`

Each part holds one file, `payload.zip`. Open the part with the password,
then open `payload.zip`, which needs no password. Any zip tool can open
`payload.zip`, including Finder and `unzip`.

## Non-ASCII passwords

zipseal derives keys from the UTF-8 bytes of the password, as 7-Zip and
libarchive do. Some older tools use another encoding, so a password with
accented or non-Latin characters may not open there. Generated passwords use
only ASCII letters and digits.
