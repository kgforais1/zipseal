"""Parse --max-size values such as "25MB", "10MiB", "2G" or "1048576" (SPEC.md §4)."""

import re
from decimal import Decimal, InvalidOperation

from zipseal.errors import UsageError

_UNITS = {
    "": 1,
    "k": 10**3,
    "kb": 10**3,
    "m": 10**6,
    "mb": 10**6,
    "g": 10**9,
    "gb": 10**9,
    "t": 10**12,
    "tb": 10**12,
    "kib": 2**10,
    "mib": 2**20,
    "gib": 2**30,
    "tib": 2**40,
}

_SIZE_RE = re.compile(r"\s*(\d+(?:\.\d+)?)\s*([A-Za-z]*)\s*")


def parse_size(text: str) -> int:
    """Return the size in bytes. Raise UsageError for anything malformed."""
    match = _SIZE_RE.fullmatch(text)
    if not match:
        raise UsageError(f"invalid size {text!r}: expected a number with an optional unit")
    number, unit = match.groups()
    multiplier = _UNITS.get(unit.lower())
    if multiplier is None:
        raise UsageError(
            f"invalid size {text!r}: unknown unit {unit!r} "
            "(use KB, MB, GB, TB, KiB, MiB, GiB, TiB or plain bytes)"
        )
    try:
        value = Decimal(number) * multiplier
    except InvalidOperation as exc:  # pragma: no cover - regex already guards this
        raise UsageError(f"invalid size {text!r}") from exc
    if value != value.to_integral_value():
        raise UsageError(f"invalid size {text!r}: not a whole number of bytes")
    size = int(value)
    if size <= 0:
        raise UsageError(f"invalid size {text!r}: must be greater than zero")
    return size
