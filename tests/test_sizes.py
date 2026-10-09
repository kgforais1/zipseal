import pytest

from zipseal.errors import UsageError
from zipseal.sizes import parse_size


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1", 1),
        ("1048576", 1048576),
        ("25MB", 25_000_000),
        ("25mb", 25_000_000),
        ("25 MB", 25_000_000),
        ("2G", 2_000_000_000),
        ("2GB", 2_000_000_000),
        ("1K", 1000),
        ("1TB", 10**12),
        ("10MiB", 10 * 2**20),
        ("1kib", 1024),
        ("2GiB", 2 * 2**30),
        ("1TiB", 2**40),
        ("1.5MB", 1_500_000),
        ("0.5KiB", 512),
    ],
)
def test_valid_sizes(text: str, expected: int) -> None:
    assert parse_size(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "MB",
        "0",
        "0MB",
        "-5MB",
        "25XB",
        "25B",
        "25MBx",
        "25 M B",
        "1.5",
        "0.0001KB",
        "1e6",
        "five",
    ],
)
def test_invalid_sizes(text: str) -> None:
    with pytest.raises(UsageError):
        parse_size(text)
