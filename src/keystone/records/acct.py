"""ACCT-FIELDS: account master record, 170 bytes (KFB-STD-003 section 1, CBL0001.cobol:41-55)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from keystone.errors import RecordLengthError
from keystone.records.packed import decode_comp3

RECORD_LENGTH = 170
CODEC = "cp037"

# (start, end) zero-based slices; 1-based offset and length from the data dictionary.
ACCT_NO = slice(0, 8)  # offset 1, X(8)
ACCT_LIMIT = slice(8, 13)  # offset 9, S9(7)V99 COMP-3
ACCT_BALANCE = slice(13, 18)  # offset 14, S9(7)V99 COMP-3
LAST_NAME = slice(18, 38)  # offset 19, X(20)
FIRST_NAME = slice(38, 53)  # offset 39, X(15)
STREET_ADDR = slice(53, 78)  # offset 54, X(25)
CITY_COUNTY = slice(78, 98)  # offset 79, X(20)
USA_STATE = slice(98, 113)  # offset 99, X(15)
RESERVED = slice(113, 120)  # offset 114, X(7)
COMMENTS = slice(120, 170)  # offset 121, X(50)


class AcctFields(BaseModel):
    """Parsed ACCT-FIELDS. Every field is PII: repr is suppressed so it cannot leak into logs."""

    model_config = ConfigDict(frozen=True)

    acct_no: str = Field(repr=False)
    limit: Decimal = Field(repr=False)
    balance: Decimal = Field(repr=False)
    last_name: str = Field(repr=False)
    first_name: str = Field(repr=False)
    street_addr: str = Field(repr=False)
    city_county: str = Field(repr=False)
    usa_state: str = Field(repr=False)
    reserved: bytes = Field(repr=False)  # preserved as-is
    comments: str = Field(repr=False)

    def to_bytes(self) -> bytes:
        """Rebuild the full 170-byte record (packed fields re-encoded)."""
        return (
            self.acct_no.encode(CODEC)
            + _encode_comp3(self.limit)
            + _encode_comp3(self.balance)
            + self.last_name.encode(CODEC)
            + self.first_name.encode(CODEC)
            + self.street_addr.encode(CODEC)
            + self.city_county.encode(CODEC)
            + self.usa_state.encode(CODEC)
            + self.reserved
            + self.comments.encode(CODEC)
        )


def _encode_comp3(value: Decimal) -> bytes:
    digits = str(int(abs(value) * 100)).zfill(9)
    return bytes.fromhex(digits + ("d" if value < 0 else "c"))


def parse_acct(raw: bytes, record_no: int) -> AcctFields:
    """Parse one 170-byte record. Wrong length raises RecordLengthError."""
    if len(raw) != RECORD_LENGTH:
        raise RecordLengthError(f"record {record_no}: length {len(raw)}, expected {RECORD_LENGTH}")
    return AcctFields(
        acct_no=raw[ACCT_NO].decode(CODEC),
        limit=decode_comp3(raw[ACCT_LIMIT], 2, record_no, "ACCT-LIMIT"),
        balance=decode_comp3(raw[ACCT_BALANCE], 2, record_no, "ACCT-BALANCE"),
        last_name=raw[LAST_NAME].decode(CODEC),
        first_name=raw[FIRST_NAME].decode(CODEC),
        street_addr=raw[STREET_ADDR].decode(CODEC),
        city_county=raw[CITY_COUNTY].decode(CODEC),
        usa_state=raw[USA_STATE].decode(CODEC),
        reserved=raw[RESERVED],
        comments=raw[COMMENTS].decode(CODEC),
    )
