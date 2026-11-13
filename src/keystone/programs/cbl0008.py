"""Port of CBL0008 (account report) with the MOD-1 OVER-LIMIT flag.

Legacy source: corpus/legacy/COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0008.cobol.
Every print line is 65 bytes (legacy PRINT-REC was 62). Detail lines carry two spaces at bytes
63-64 and the OVER-LIMIT flag at byte 65. No ASA carriage-control byte is written.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
)
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from keystone.errors import FieldOverflowError, RecordLengthError
from keystone.logging import get_logger, mask_account
from keystone.records.acct import RECORD_LENGTH, AcctFields, parse_acct

KFB_CONTEXT = Context(
    prec=31,
    rounding=ROUND_HALF_UP,
    traps=[InvalidOperation, DivisionByZero, Overflow],
)

LINE_LENGTH = 65
PROGRAM = "CBL0008"
log = get_logger(__name__)
_CENT = Decimal("0.01")
_CODEC = "cp037"


# --- input record (layout lives in keystone.records.acct) -------------------------------------

AcctRecord = AcctFields


def parse_record(raw: bytes, record_no: int) -> AcctFields:
    """Parse one 170-byte ACCT-FIELDS record."""
    return parse_acct(raw, record_no)


def read_records(path: Path) -> Iterator[AcctFields]:
    """Yield records from an ACCTREC file opened 'rb'; exhaustion is AT END."""
    with open(path, "rb") as fh:
        record_no = 0
        while chunk := fh.read(RECORD_LENGTH):
            record_no += 1
            yield parse_record(chunk, record_no)


# --- arithmetic and edited pictures ----------------------------------------------------------


def add_to_total(total: Decimal, amount: Decimal) -> Decimal:
    """COMPUTE total = total + amount into S9(9)V99 COMP-3: no ROUNDED, so truncate."""
    result = KFB_CONTEXT.add(total, amount).quantize(_CENT, rounding=ROUND_DOWN)
    if abs(result) >= Decimal(10) ** 9:
        raise FieldOverflowError("total exceeds S9(9)V99")
    return result


def format_edited(value: Decimal, int_digits: int, width: int) -> str:
    """Edit a value like PIC $$..9.99: floating $, no sign, high-order digits dropped.

    int_digits is the number of integer digit positions (the first $ is only the symbol).
    """
    cents = int(abs(value).quantize(_CENT, rounding=ROUND_DOWN) * 100)
    integer, frac = divmod(cents, 100)
    integer %= 10**int_digits  # silent high-order truncation, as in the legacy MOVE
    return f"${integer:,}.{frac:02d}".rjust(width)


def edit_detail_amount(value: Decimal) -> str:
    """PIC $$,$$$,$$9.99 (13 bytes, 7 integer digits)."""
    return format_edited(value, 7, 13)


def edit_total_amount(value: Decimal) -> str:
    """PIC $$$,$$$,$$9.99 (14 bytes, 8 integer digits)."""
    return format_edited(value, 8, 14)


# --- print lines -----------------------------------------------------------------------------


def over_limit(limit: Decimal, balance: Decimal) -> str:
    """'Y' when balance is greater than limit, otherwise 'N' (equal is 'N')."""
    return "Y" if balance > limit else "N"


class DetailLine(BaseModel):
    """One 65-byte detail line: legacy PRINT-REC (62) + 2 spaces + OVER-LIMIT."""

    model_config = ConfigDict(frozen=True)

    acct_no: str = Field(max_length=8)
    last_name: str = Field(max_length=20)
    limit: Decimal
    balance: Decimal

    @model_validator(mode="after")
    def _check_length(self) -> DetailLine:
        if len(self.render()) != LINE_LENGTH:
            raise RecordLengthError("detail line is not 65 bytes")
        return self

    @property
    def over_limit(self) -> str:
        return over_limit(self.limit, self.balance)

    def render(self) -> str:
        return (
            f"{self.acct_no:<8}"
            "  "
            f"{self.last_name:<20}"
            "  "
            f"{edit_detail_amount(self.limit)}"
            "  "
            f"{edit_detail_amount(self.balance)}"
            "  "  # legacy trailing FILLER X(02), bytes 61-62
            "  "  # new spacer, bytes 63-64
            f"{self.over_limit}"  # new OVER-LIMIT, byte 65
        )


def _pad(text: str) -> str:
    """Fit a header/trailer group to the 65-byte print record."""
    return text[:LINE_LENGTH].ljust(LINE_LENGTH)


def header_lines(run_date: date) -> list[str]:
    """HEADER-1, HEADER-2, blank line, HEADER-3, HEADER-4."""
    header_1 = "Financial Report for"
    header_2 = f"Year {run_date.year:04d}  Month {run_date.month:02d}  Day {run_date.day:02d}"
    header_3 = "Account " + "  " + "Last Name " + " " * 15 + "Limit " + " " * 6 + "Balance "
    header_4 = "-" * 8 + "  " + "-" * 10 + " " * 15 + "-" * 10 + "  " + "-" * 13
    return [_pad(t) for t in (header_1, header_2, "", header_3, header_4)]


def trailer_lines(tlimit: Decimal, tbalance: Decimal) -> list[str]:
    """TRAILER-1 and TRAILER-2."""
    trailer_1 = " " * 31 + "-" * 14 + " " + "-" * 14
    trailer_2 = (
        " " * 22 + "Totals =" + " " + edit_total_amount(tlimit) + " " + edit_total_amount(tbalance)
    )
    return [_pad(trailer_1), _pad(trailer_2)]


@dataclass(frozen=True)
class Report:
    lines: tuple[str, ...]
    tlimit: Decimal
    tbalance: Decimal


def build_report(records: Iterable[AcctFields], run_date: date) -> Report:
    """Build the full report. The run date is not masked."""
    tlimit = Decimal("0.00")
    tbalance = Decimal("0.00")
    details: list[str] = []
    for rec in records:
        tlimit = add_to_total(tlimit, rec.limit)
        tbalance = add_to_total(tbalance, rec.balance)
        details.append(
            DetailLine(
                acct_no=rec.acct_no,
                last_name=rec.last_name,
                limit=rec.limit,
                balance=rec.balance,
            ).render()
        )
    lines = header_lines(run_date) + details + trailer_lines(tlimit, tbalance)
    return Report(lines=tuple(lines), tlimit=tlimit, tbalance=tbalance)


def write_report(report: Report, path: Path) -> None:
    """Write fixed 65-byte records (cp037, no newline, no ASA byte)."""
    with open(path, "wb") as fh:
        fh.writelines(line.encode(_CODEC) for line in report.lines)


def _logged(records: Iterable[AcctFields], run_id: str) -> Iterator[AcctFields]:
    """Log each record read: record number and masked account only (no names, no amounts)."""
    for record_no, rec in enumerate(records, start=1):
        log.debug(
            "record_read",
            extra={
                "program": PROGRAM,
                "run_id": run_id,
                "event": "record_read:" + mask_account(rec.acct_no),
                "record_no": record_no,
            },
        )
        yield rec


def run(acctrec: Path, prtline: Path, run_date: date | None = None) -> Report:
    """Equivalent of the CBL0008 job step."""
    run_id = uuid.uuid4().hex
    base = {"program": PROGRAM, "run_id": run_id, "record_no": None}
    log.info("run_start", extra={**base, "event": "run_start"})
    report = build_report(_logged(read_records(acctrec), run_id), run_date or datetime.now().date())
    write_report(report, prtline)
    records_read = len(report.lines) - 7
    log.info(
        "run_end",
        extra={
            **base,
            "event": f"run_end records_read={records_read} records_written={len(report.lines)}",
        },
    )
    return report
