# Investigation: stream-zip and stream-unzip behavior

Date: 2026-10-08
Versions: `stream-zip` 0.0.84, `stream-unzip` 0.0.101, Python 3.12 via `uvx`
Feeds: [`../plans/2026-10-08-v1-implementation.md`](../plans/2026-10-08-v1-implementation.md), `SPEC.md` §6.2, §6.6, §6.7

## Question

Do the libraries behave the way `SPEC.md` assumed for AES writing,
verification, size accounting and the `--hide-names` outer layer?

## Method

Small scripts run with `uvx --with stream-zip --with stream-unzip python`.
Each one built archives in memory and inspected headers, sizes, or
exceptions. A Grok 4.7 review then read the library source at the same
versions. Claims marked "source" come from that reading. Claims marked
"tested" were run here.

## Findings

| # | Finding | Evidence |
|---|---|---|
| 1 | With `password=`, entries are AE-2 (vendor version 2), AES-256 (strength 3), method 99, with general purpose flag `0x809` (encrypted, data descriptor, UTF-8). The CRC field is 0. | Tested. Local header and AES extra `0199 0700 0200 4145 03 0800` |
| 2 | A wrong password raises `IncorrectAESPasswordError` in `stream_unzip`. | Tested |
| 3 | `NO_COMPRESSION_32/64` take `(uncompressed_size, crc_32)`. They cannot stream an entry whose size and CRC are not yet known. | Tested (signature) |
| 4 | `ZIP_AUTO(size, level)` ignores `stream_zip(get_compressobj=…)`. `ZIP_32` uses it. | Tested. A counting wrapper saw no calls under `ZIP_AUTO` and calls under `ZIP_32`. |
| 5 | `ZIP_AUTO(10)` given 200,000 bytes writes a 200,249-byte archive with no error. Size changes are not detected. | Tested |
| 6 | The default compressor is raw deflate at level 9. | Tested (source of the default lambda) |
| 7 | `stream_zip` takes `password: str`. `stream_unzip` takes `password: bytes` and by default also accepts ZipCrypto and AE-1 through `allowed_encryption_mechanisms`. | Tested (signatures) |
| 8 | `stream-zip` pulls the next member only after the current one is finished. Output is re-chunked to `chunk_size` (65,536 by default), with a flush after each local header. | Source |
| 9 | Extra fields per entry: extended timestamp 9 bytes, AES 11 bytes, Zip64 local 20 bytes when `ZIP_64`. | Source |
| 10 | Once there are more than 65,535 members, the end records are upgraded to Zip64 (98 bytes instead of 22). | Source |

Measured archive sizes, one entry each, password set:

| Input | `ZIP_32` total | `ZIP_64` total |
|---|---|---|
| empty file | 186 B | 318 B |
| 100,000 random bytes | 100,219 B | 100,351 B |
| 1,000,000 random bytes | 1,000,496 B | 1,000,628 B |

The 1 MB row leaves 310 bytes after removing the 186-byte empty baseline.
That is 62 blocks × 5 bytes, which matches the "5 bytes per 16 KiB block"
deflate expansion term.

## Consequences

- Choose `ZIP_32` or `ZIP_64` explicitly and never use `ZIP_AUTO` (findings 4
  and 5).
- Count bytes read from each source and fail on a mismatch (finding 5).
- Verify by HMAC plus SHA-256, with encryption limited to AE-2 AES-256
  (findings 1 and 7).
- Use deflate level 0 for the `--hide-names` outer entry (finding 3).
- Reserve central-directory entries for every admitted member and 98 bytes
  of end records (findings 8 and 10).

## Not yet tested

- Exact computed versus measured local size per member (Phase 4 test).
- Interop with `7zz`, Keka and Archive Utility for Zip64 and split output.
