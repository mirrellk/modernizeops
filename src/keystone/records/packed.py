"""COMP-3 (packed decimal) decoding."""

from __future__ import annotations

from decimal import Decimal

from keystone.errors import InvalidNumericDataError

# IBM sign nibbles: A, C, E, F are positive (C and F preferred); B and D are negative.
_POSITIVE = frozenset("acef")
_NEGATIVE = frozenset("bd")


def decode_comp3(raw: bytes, scale: int, record_no: int, field: str) -> Decimal:
    """Decode a signed COMP-3 field; invalid nibbles raise InvalidNumericDataError."""
    nibbles = raw.hex()
    digits, sign = nibbles[:-1], nibbles[-1]
    if sign not in _POSITIVE | _NEGATIVE or not digits.isdigit():
        raise InvalidNumericDataError(f"record {record_no}: invalid packed data in {field}")
    value = Decimal(int(digits)).scaleb(-scale)
    return -value if sign in _NEGATIVE else value
