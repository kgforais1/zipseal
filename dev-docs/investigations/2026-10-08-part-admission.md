# Investigation: part admission design

Date: 2026-10-08
Feeds: [`../plans/archive/2026-10-08-v1-implementation.md`](../plans/archive/2026-10-08-v1-implementation.md) Phase 4, `SPEC.md` §6.2

## Decision

Design A, exact counting, is implemented in `src/zipseal/write.py`.

`stream_zip` receives a `get_compressobj` factory that returns a wrapper around
`zlib.compressobj(level, DEFLATED, -15, 8)`. The wrapper counts the bytes that
`compress()` and `flush()` return. `stream-zip` finishes one member before it
pulls the next from the member iterator. At each pull, the iterator adds the
previous member's exact local size to the part's budget:

```
local header (30 + name + AES extra 11 + Zip64 extra 20 if 64-bit)
+ 28 AES overhead + compressed bytes + data descriptor (16, 24, or 0 for folders)
```

Then it applies the §6.2 admission rule to the next entry. If the entry does
not fit, the iterator ends and the part closes.

## Evidence

- After every part, `write_part` compares the predicted size (exact local
  bytes, plus the central entries, plus 22 or 98 bytes of end records) with
  the bytes actually written. Any difference raises an error instead of
  publishing. This runs in production, not only in tests, so a future
  `stream-zip` that writes different framing is caught on its first run.
- `tests/test_plan.py::test_framing_is_exact` checks the framing model against
  real archives for files and folders, in Zip32 and Zip64, with long and
  multi-byte names.
- The whole suite passes with the runtime check enabled, including a
  `hypothesis` property test over random sizes, name lengths and caps.

## Measured slack

- Random 200 KB files with a 4 MB cap gave parts of 3.80 MB, 3.80 MB and
  1.70 MB. Each part stopped because the next whole file would not fit.
  That slack is the file granularity, not the bound.
- The bound only matters for the next entry's admission. Incompressible data
  is within about 0.03% of its bound. Text is far below its bound, so a part
  can close early when the next text file's bound does not fit, even though
  its compressed size would have. `test_compressible_bound_slack_is_bounded`
  keeps parts at least half full in that case. `--tight` (in `TODO.md`)
  would remove this slack.

## Design B

Design B (emitted bytes plus a `chunk_size` margin) was not needed. It
remains the fallback if the runtime accounting check ever fails on a new
`stream-zip` release.
