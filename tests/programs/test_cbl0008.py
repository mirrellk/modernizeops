"""Tests for the CBL0008 port with the MOD-1 OVER-LIMIT flag (synthetic/sample data only)."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from keystone.errors import (
    FieldOverflowError,
    InvalidNumericDataError,
    RecordLengthError,
)
from keystone.programs import cbl0008
from keystone.programs.cbl0008 import (
    AcctRecord,
    DetailLine,
    add_to_total,
    build_report,
    edit_detail_amount,
    edit_total_amount,
    over_limit,
    parse_record,
    read_records,
)

SAMPLE = (
    Path(__file__).resolve().parents[2]
    / "corpus/legacy/COBOL Programming Course #2 - Learning COBOL/Labs/data/data"
)
RUN_DATE = date(2026, 11, 12)


# --- independent helpers (do not use the code under test) ------------------------------------


def _raw_records() -> list[bytes]:
    data = SAMPLE.read_bytes()
    return [data[i : i + 170] for i in range(0, len(data), 170)]


def _packed(raw: bytes) -> Decimal:
    h = raw.hex()
    sign = -1 if h[-1] == "d" else 1
    return sign * Decimal(int(h[:-1])) / 100


def _sample_values() -> list[tuple[str, str, Decimal, Decimal]]:
    out = []
    for r in _raw_records():
        out.append(
            (
                r[0:8].decode("cp037"),
                r[18:38].decode("cp037"),
                _packed(r[8:13]),
                _packed(r[13:18]),
            )
        )
    return out


def _pack(value: Decimal, nbytes: int = 5) -> bytes:
    digits = str(int(abs(value) * 100)).zfill(nbytes * 2 - 1)
    return bytes.fromhex(digits + ("d" if value < 0 else "c"))


def _make_raw(acct: str, name: str, limit: Decimal, balance: Decimal) -> bytes:
    raw = (
        acct.ljust(8).encode("cp037")
        + _pack(limit)
        + _pack(balance)
        + name.ljust(20).encode("cp037")
    )
    return raw + b"\x40" * (170 - len(raw))


def _synthetic(limit: str, balance: str) -> AcctRecord:
    return parse_record(_make_raw("SYN00001", "TESTER", Decimal(limit), Decimal(balance)), 1)


@pytest.fixture(scope="module")
def sample_report():
    return build_report(read_records(SAMPLE), RUN_DATE)


# --- AC 1, 2: totals -------------------------------------------------------------------------


def test_totals_sample_tlimit_equals_sum_and_printed_value(sample_report):
    """AC1: TLIMIT equals the sum of ACCT-LIMIT over all records and the printed TLIMIT."""
    expected = sum(v[2] for v in _sample_values())
    assert len(_sample_values()) == 45
    assert sample_report.tlimit == expected == Decimal("47500000.00")
    assert sample_report.lines[-1][31:45].strip() == "$47,500,000.00"


def test_totals_sample_tbalance_equals_sum_and_printed_value(sample_report):
    """AC2: TBALANCE equals the sum of ACCT-BALANCE over all records and the printed value."""
    expected = sum(v[3] for v in _sample_values())
    assert sample_report.tbalance == expected == Decimal("23004207.47")
    assert sample_report.lines[-1][46:60].strip() == "$23,004,207.47"


# --- AC 3, 4, 5: OVER-LIMIT --------------------------------------------------------------------


def test_over_limit_balance_above_limit_is_y():
    """AC3: balance greater than limit gives OVER-LIMIT 'Y' (sample records 5, 6, 35)."""
    vals = _sample_values()
    for n in (5, 6, 35):
        _, _, limit, balance = vals[n - 1]
        assert balance > limit
        assert over_limit(limit, balance) == "Y"
    assert over_limit(Decimal("10000.00"), Decimal("10000.01")) == "Y"


def test_over_limit_balance_equal_limit_is_n():
    """AC4: synthetic test-only record with balance equal to limit gives 'N'."""
    rec = _synthetic("5000.00", "5000.00")
    assert over_limit(rec.limit, rec.balance) == "N"
    line = DetailLine(
        acct_no=rec.acct_no, last_name=rec.last_name, limit=rec.limit, balance=rec.balance
    ).render()
    assert line[64] == "N"
    assert all(v[2] != v[3] for v in _sample_values())  # never added to the sample


def test_over_limit_balance_below_limit_is_n():
    """AC5: balance less than limit gives OVER-LIMIT 'N' (sample records 1, 2, 3)."""
    vals = _sample_values()
    for n in (1, 2, 3):
        _, _, limit, balance = vals[n - 1]
        assert balance < limit
        assert over_limit(limit, balance) == "N"


def test_over_limit_sample_flags_match_independent_comparison(sample_report):
    """AC3/AC5: every sample detail line flag matches balance vs limit (6 Y, 39 N)."""
    detail = sample_report.lines[5:-2]
    flags = [line[64] for line in detail]
    assert flags == ["Y" if v[3] > v[2] else "N" for v in _sample_values()]
    assert flags.count("Y") == 6
    assert flags.count("N") == 39


def test_over_limit_negative_balance_is_n():
    """AC5: a negative balance (signed COMP-3) is below the limit."""
    assert over_limit(Decimal("100.00"), Decimal("-5.00")) == "N"


# --- AC 6, 7: line lengths -----------------------------------------------------------------


def test_detail_line_length_65_with_spaces_then_flag(sample_report):
    """AC6: each detail line is 65 bytes, bytes 63-64 spaces, byte 65 is Y or N."""
    for line in sample_report.lines[5:-2]:
        assert len(line) == 65
        assert line[62:64] == "  "
        assert line[64] in "YN"


def test_every_print_line_is_65_bytes(sample_report):
    """AC7: header, detail and totals lines are all 65 bytes; 52 lines for 45 records."""
    assert len(sample_report.lines) == 52
    assert {len(line) for line in sample_report.lines} == {65}


def test_header_trailer_lines_padded_with_spaces_on_right(sample_report):
    """AC7: header and totals lines carry only trailing spaces beyond their content."""
    lines = sample_report.lines
    assert lines[2] == " " * 65
    assert lines[-1][60:] == " " * 5
    assert lines[-2] == " " * 31 + "-" * 14 + " " + "-" * 14 + " " * 5


# --- AC 8: headers ---------------------------------------------------------------------------


def test_headers_text_unchanged_and_no_over_limit_heading(sample_report):
    """AC8: HEADER-1 to HEADER-4 text is unchanged and OVER-LIMIT has no heading."""
    lines = sample_report.lines
    assert lines[0] == "Financial Report for".ljust(65)
    assert lines[1] == "Year 2026  Month 11  Day 12".ljust(65)
    h3 = "Account " + "  " + "Last Name " + " " * 15 + "Limit " + " " * 6 + "Balance "
    assert lines[3] == h3.ljust(65)
    assert lines[4] == ("-" * 8 + "  " + "-" * 10 + " " * 15 + "-" * 10 + "  " + "-" * 13).ljust(65)
    assert all("OVER" not in line.upper() for line in lines[:5])
    assert lines[3][62:] == "   " and lines[4][62:] == "   "


# --- AC 9: logical record, no ASA --------------------------------------------------------------


def test_output_file_has_no_asa_byte_and_fixed_65_byte_records(tmp_path):
    """AC9: output is fixed 65-byte logical records with no carriage-control byte."""
    out = tmp_path / "prtline"
    report = cbl0008.run(SAMPLE, out, RUN_DATE)
    raw = out.read_bytes()
    assert len(raw) == 65 * 52
    first = raw[:65].decode("cp037")
    assert first.startswith("Financial Report for")  # byte 1 is data, not an ASA character
    assert [raw[i : i + 65].decode("cp037") for i in range(0, len(raw), 65)] == list(report.lines)


# --- AC 10: byte-for-byte versus legacy layout --------------------------------------------------


def test_report_matches_legacy_layout_except_new_bytes_padding_and_run_date(tmp_path):
    """AC10: apart from bytes 63-65, padding and the masked run date, equals CBL0008 output.

    Reference per business decision 04-decision-1.md (Jira MOD-1 comment 10009): no legacy
    CBL0008 golden file exists, so the expected report is rebuilt from CBL0008.cobol:60-109.
    It is compared as encoded cp037 bytes, as written by the module. Replace the rebuilt
    reference with a real PRTLINE capture if one is obtained.
    """
    out = tmp_path / "prtline"
    cbl0008.run(SAMPLE, out, RUN_DATE)
    got = out.read_bytes()
    assert len(got) == 65 * 52
    got_records = [got[i : i + 65] for i in range(0, len(got), 65)]

    def enc(text: str) -> bytes:
        return text.encode("cp037")

    hash_byte = enc("#")
    h3 = "Account " + "  " + "Last Name " + " " * 15 + "Limit " + " " * 6 + "Balance "
    h4 = "-" * 8 + "  " + "-" * 10 + " " * 15 + "-" * 10 + "  " + "-" * 13
    legacy: list[bytes] = [
        enc("Financial Report for".ljust(62)),
        enc("Year ####  Month ##  Day ##".ljust(62)),
        enc(" " * 62),
        enc(h3.ljust(62)),
        enc(h4.ljust(62)),
    ]
    legacy += [
        enc(
            f"{a:<8}  {n:<20}  {('$' + format(lim, ',.2f')):>13}  {('$' + format(bal, ',.2f')):>13}  "
        )
        for a, n, lim, bal in _sample_values()
    ]
    legacy.append(enc((" " * 31 + "-" * 14 + " " + "-" * 14).ljust(62)))
    legacy.append(
        enc((" " * 22 + "Totals =" + " " + "$47,500,000.00" + " " + "$23,004,207.47").ljust(62))
    )
    assert len(legacy) == 52 and {len(x) for x in legacy} == {62}

    for i, (rec, expected) in enumerate(zip(got_records, legacy, strict=True)):
        if i == 1:  # mask the run-date digits: Year (6-9), Month (18-19), Day (26-27)
            rec = (
                rec[:5]
                + hash_byte * 4
                + rec[9:17]
                + hash_byte * 2
                + rec[19:25]
                + hash_byte * 2
                + rec[27:]
            )
        # bytes 63-65 of detail lines are new; on other lines they are padding (cp037 spaces)
        assert rec[:62] == expected, f"line {i + 1}"
        if not 5 <= i < 50:
            assert rec[62:] == enc("   ")
    # first sample record, hand-checked against the raw bytes
    assert got_records[5] == enc(
        "17891797  WASHINGTON            " + "   $10,000.00" + "  " + "      $188.74" + "  " + "  N"
    )


# --- AC 11: run date not masked in module output ----------------------------------------------


def test_run_date_is_not_masked_in_module_output(sample_report):
    """AC11: the module prints the actual run date digits (bytes 6-9, 18-19, 26-27)."""
    h2 = sample_report.lines[1]
    assert h2[5:9] == "2026" and h2[17:19] == "11" and h2[25:27] == "12"
    assert "#" not in h2


# --- standards: edited PIC, arithmetic, bad data -------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", "        $0.00"),
        ("5", "        $5.00"),
        ("0.01", "        $0.01"),
        ("9999999.99", "$9,999,999.99"),
        ("-1234.50", "    $1,234.50"),
    ],
)
def test_edit_detail_amount_zero_one_digit_full_negative(value, expected):
    """Edited PIC $$,$$$,$$9.99: zero, one digit, all positions filled, negative unsigned."""
    assert edit_detail_amount(Decimal(value)) == expected
    assert len(expected) == 13


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", "         $0.00"),
        ("99999999.99", "$99,999,999.99"),
        ("-5.25", "         $5.25"),
        ("100000000.00", "         $0.00"),  # legacy defect: high-order digit dropped
        ("123456789.12", "$23,456,789.12"),
    ],
)
def test_edit_total_amount_boundaries_and_high_order_truncation(value, expected):
    """Edited PIC $$$,$$$,$$9.99: boundaries; 9 integer digits lose the high digit silently."""
    assert edit_total_amount(Decimal(value)) == expected
    assert len(expected) == 14


def test_add_to_total_half_cent_truncates_not_rounds():
    """COMPUTE TLIMIT/TBALANCE has no ROUNDED: a half-cent result truncates."""
    assert add_to_total(Decimal("1.00"), Decimal("0.005")) == Decimal("1.00")
    assert add_to_total(Decimal("1.00"), Decimal("0.015")) == Decimal("1.01")
    assert add_to_total(Decimal("-1.00"), Decimal("-0.005")) == Decimal("-1.00")


def test_add_to_total_past_s9_9_v99_raises_overflow():
    """TLIMIT S9(9)V99: 999,999,999.99 fits; one cent more raises FieldOverflowError."""
    assert add_to_total(Decimal("999999999.98"), Decimal("0.01")) == Decimal("999999999.99")
    with pytest.raises(FieldOverflowError):
        add_to_total(Decimal("999999999.99"), Decimal("0.01"))


def test_parse_record_boundary_amounts():
    """ACCT-LIMIT S9(7)V99 boundaries parse exactly, including negative."""
    rec = parse_record(_make_raw("A", "B", Decimal("9999999.99"), Decimal("-9999999.99")), 1)
    assert rec.limit == Decimal("9999999.99")
    assert rec.balance == Decimal("-9999999.99")


def test_parse_record_invalid_packed_nibble_raises_with_record_and_field():
    """Bad packed data raises InvalidNumericDataError naming record and field."""
    raw = bytearray(_make_raw("A", "B", Decimal("1.00"), Decimal("1.00")))
    raw[10] = 0xAB  # invalid digit nibble in ACCT-LIMIT
    with pytest.raises(InvalidNumericDataError, match=r"record 7.*ACCT-LIMIT"):
        parse_record(bytes(raw), 7)
    raw = bytearray(_make_raw("A", "B", Decimal("1.00"), Decimal("1.00")))
    raw[17] = 0x15  # invalid sign nibble (A is valid positive) in ACCT-BALANCE
    with pytest.raises(InvalidNumericDataError, match="ACCT-BALANCE"):
        parse_record(bytes(raw), 1)


def test_parse_record_short_or_long_record_raises_length_error():
    """A record that is not 170 bytes raises RecordLengthError."""
    good = _make_raw("A", "B", Decimal("1.00"), Decimal("1.00"))
    with pytest.raises(RecordLengthError):
        parse_record(good[:169], 1)
    with pytest.raises(RecordLengthError):
        parse_record(good + b"\x40", 1)


def test_read_records_partial_trailing_record_raises(tmp_path):
    """A file that is not a multiple of 170 bytes raises RecordLengthError (xdata case)."""
    f = tmp_path / "acctrec"
    f.write_bytes(_make_raw("A", "B", Decimal("1.00"), Decimal("1.00")) + b"\x40" * 10)
    with pytest.raises(RecordLengthError, match="record 2"):
        list(read_records(f))


def test_run_logs_no_account_numbers_or_names(tmp_path, caplog):
    """PII: logs are emitted, hold only masked accounts, and never names or amounts."""
    with caplog.at_level(logging.DEBUG):
        cbl0008.run(SAMPLE, tmp_path / "prtline", RUN_DATE)
    assert caplog.records, "module must log run and record events"
    text = " ".join(
        f"{r.getMessage()} {getattr(r, 'event', '')} {getattr(r, 'program', '')}"
        for r in caplog.records
    )
    assert "****1797" in text  # first sample record, masked to last 4
    assert "run_start" in text and "records_read=45 records_written=52" in text
    for acct, name, limit, balance in _sample_values():
        assert acct not in text and name.strip() not in text
        assert f"{limit:,.2f}" not in text and f"{balance:,.2f}" not in text


def test_json_formatter_emits_required_fields_and_masks_account(tmp_path, caplog):
    """Standards 4: JSON log lines carry timestamp, level, program, run_id, event, record_no."""
    import json

    from keystone.logging import JsonFormatter, mask_account

    assert mask_account("17891797") == "****1797"
    with caplog.at_level(logging.DEBUG):
        cbl0008.run(SAMPLE, tmp_path / "prtline", RUN_DATE)
    rec = next(r for r in caplog.records if getattr(r, "record_no", None) == 1)
    data = json.loads(JsonFormatter().format(rec))
    assert set(data) == {"timestamp", "level", "program", "run_id", "event", "record_no"}
    assert data["program"] == "CBL0008" and data["record_no"] == 1 and data["level"] == "DEBUG"
    assert "17891797" not in json.dumps(data)


@pytest.mark.parametrize(
    ("sign", "expected"),
    [
        ("c", "12.34"),
        ("f", "12.34"),
        ("a", "12.34"),
        ("e", "12.34"),
        ("d", "-12.34"),
        ("b", "-12.34"),
    ],
)
def test_decode_comp3_accepts_all_ibm_sign_nibbles(sign, expected):
    """IBM packed sign nibbles: A, C, E, F positive; B, D negative."""
    from keystone.records.packed import decode_comp3

    assert decode_comp3(bytes.fromhex("000001234" + sign), 2, 1, "X") == Decimal(expected)


def test_decode_comp3_invalid_sign_nibble_raises():
    """Sign nibbles 0-9 are invalid packed data."""
    from keystone.records.packed import decode_comp3

    with pytest.raises(InvalidNumericDataError, match="record 3.*ACCT-LIMIT"):
        decode_comp3(bytes.fromhex("0000123405"), 2, 3, "ACCT-LIMIT")


def test_acct_fields_layout_roundtrips_170_bytes_and_hides_pii_in_repr():
    """Records layout: 170 bytes round-trip; repr exposes no field values."""
    from keystone.records.acct import parse_acct

    raw = _raw_records()[0]
    rec = parse_acct(raw, 1)
    assert rec.to_bytes() == raw and len(raw) == 170
    assert "WASHINGTON" not in repr(rec) and "17891797" not in repr(rec)
