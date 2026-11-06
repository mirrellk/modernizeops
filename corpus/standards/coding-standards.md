# Keystone Federal Bank: Python Modernization Coding Standards

| | |
|---|---|
| Document ID | KFB-STD-001 |
| Applies to | Python 3.12 code that replaces or re-implements COBOL programs in `corpus/legacy` |
| Companion documents | `pic-mapping.md` (KFB-STD-002), `data-dictionary.md` (KFB-STD-003) |

Keystone Federal Bank is a fictional institution. The rules below are written for the ModernizeOps project. Citations in the form `file:line` are relative to `corpus/legacy/`.

The key words **MUST**, **MUST NOT**, **SHOULD** and **MAY** are used as in RFC 2119.

---

## 1. Behavioral equivalence is the goal

A modernized program MUST produce byte-for-byte the same output records as the COBOL program it replaces, for the same input. Where the legacy behavior is a defect, the defect MUST be reproduced first, covered by a test, and only then fixed in a separate, reviewed change that names the defect.

## 2. Money and decimal arithmetic

### 2.1 Use `Decimal`, never `float`

- Every monetary amount and every field with an implied decimal point (`V` in its PIC) MUST be a `decimal.Decimal`.
- `float`, `round()` on floats and `math` functions MUST NOT touch money. Floats cannot represent `0.10` exactly. COBOL fixed-point arithmetic can.
- Construct `Decimal` from `str` or `int`, never from a `float`: `Decimal("19.99")`, not `Decimal(19.99)`.

Legacy money fields are packed decimal with two decimal places, for example `ACCT-LIMIT PIC S9(7)V99 COMP-3` (`COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0001.cobol:44`).

### 2.2 Precision context

Set an explicit decimal context per module that does money arithmetic. Do not rely on the global default.

```python
from decimal import (
    ROUND_HALF_UP, Context, Decimal, DivisionByZero, InvalidOperation, Overflow,
)

KFB_CONTEXT = Context(prec=31, rounding=ROUND_HALF_UP, traps=[InvalidOperation, DivisionByZero, Overflow])
```

`prec=31` covers the largest fixed-point intermediate Enterprise COBOL produces (ARITH(EXTEND)). Programs that need a different value MUST document why.

### 2.3 Rounding must match the COBOL statement

COBOL rounds only when the statement says `ROUNDED`. Otherwise it **truncates** toward zero. The Python code MUST match each statement:

| COBOL statement | Python |
|---|---|
| `COMPUTE X ROUNDED = expr` | `expr.quantize(SCALE, rounding=ROUND_HALF_UP)` |
| `COMPUTE X = expr` (no `ROUNDED`) | `expr.quantize(SCALE, rounding=ROUND_DOWN)` |
| `ADD` / `SUBTRACT` / `MULTIPLY` / `DIVIDE ... GIVING X ROUNDED` | same as `ROUNDED` row |
| any of the above without `ROUNDED` | same as truncation row |

`SCALE` is `Decimal(1).scaleb(-n)` where `n` is the number of digits after `V` in the receiving field's PIC (`Decimal("0.01")` for `V99`).

`ROUND_HALF_UP` rounds halves away from zero (2.345 → 2.35, −2.345 → −2.35), which matches COBOL `ROUNDED` in its default mode. Do **not** use `ROUND_HALF_EVEN` (banker's rounding, the `Decimal` default) unless the COBOL source explicitly uses `ROUNDED MODE NEAREST-EVEN`.

> **Corpus note.** No program in `corpus/legacy` uses `ROUNDED`. Every arithmetic statement, such as `COMPUTE TLIMIT = TLIMIT + ACCT-LIMIT` (`COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0010.cobol:173`), truncates to the receiving field. Ports of these programs MUST use `ROUND_DOWN`. `ROUND_HALF_UP` applies only where a `ROUNDED` phrase exists.

Round once, when assigning to the receiving field, not at intermediate steps. COBOL keeps intermediate results at full precision.

### 2.4 Size errors and overflow

COBOL silently truncates high-order digits when a result does not fit the receiving PIC, unless `ON SIZE ERROR` is coded. None of the corpus programs code `ON SIZE ERROR`. Ports MUST:

1. Check that the quantized result fits the receiving field's digit count (`S9(7)V99` → at most 7 integer digits).
2. Raise `FieldOverflowError` (see §5) instead of truncating silently.
3. Have a test showing the legacy truncation, so the change in behavior is visible and approved.

### 2.5 Signs

An unsigned PIC (`9(7)V99`) stores the absolute value. Assigning a negative result to it drops the sign. Ports MUST raise `SignViolationError` instead, unless the program's spec says the sign is dropped on purpose.

## 3. Fixed-width record parsing

### 3.1 One layout definition per record

- Every record layout in `data-dictionary.md` MUST have exactly one Python definition in `src/keystone/records/`, for example a frozen `pydantic` model plus a field specification of `(name, offset, length, pic, usage)`.
- Offsets and lengths come from the data dictionary, never re-derived by hand in program code.
- The layout MUST assert its total length (`ACCT-FIELDS` is 170 bytes; see `data-dictionary.md`). A record of the wrong length MUST raise `RecordLengthError`.

### 3.2 Bytes in, bytes out

- Read files in binary mode (`open(path, "rb")`). Fixed-width records MUST NOT go through text-mode reads that translate newlines or decode before slicing.
- Slice by byte offset, then decode each field with the codec and rules in `pic-mapping.md`.
- Host datasets are EBCDIC. Use codec `cp037` unless the dataset's transfer record says otherwise. Packed (`COMP-3`) and binary (`COMP`) fields MUST NOT be passed through a codepage decode, because the bytes are not characters.
- Writers MUST rebuild the full record (including `FILLER` and `RESERVED` bytes) to the exact length.

### 3.3 Text fields

- On read, `PIC X(n)` values are right-stripped of spaces for business logic, but the raw bytes MUST be kept when a field must be written back unchanged.
- On write, left-justify and pad with spaces to `n`. Values longer than `n` raise `FieldOverflowError`. Never truncate silently.

### 3.4 Numeric validation

COBOL programs abend with a data exception (S0C7) on invalid packed or zoned data. Ports MUST validate every numeric field on read and raise `InvalidNumericDataError` with the record number and field name. They MUST NOT return zero or skip the record silently.

## 4. Logging

- Use the standard `logging` module through `keystone.logging.get_logger(__name__)`. `print()` MUST NOT be used for diagnostics.
- Log records MUST be structured (JSON) with at least: `timestamp` (UTC, ISO 8601), `level`, `program` (the legacy PROGRAM-ID being replaced, e.g. `CBL0001`), `run_id`, `event`, and `record_no` where applicable.
- Fields flagged **PII = Yes** in `data-dictionary.md` MUST NOT be logged in clear text. Mask account numbers to their last 4 characters (`****1809`). Omit names and addresses. Free-text fields flagged **Possible** MUST be omitted.
- Money amounts MAY be logged only at `DEBUG` level, and never next to an unmasked account number.
- Level guide: `INFO` for run start/end and record counts; `WARNING` for recoverable data issues; `ERROR` for a record or run failure; `DEBUG` for field-level traces (disabled in production).
- Every run MUST log the number of input records read and output records written, which corresponds to the counts checked at COBOL end of file.

## 5. Error handling

### 5.1 Exception hierarchy

All project errors derive from one base class in `keystone.errors`:

```
KeystoneError
├── RecordError                (carries file name, record_no, field name)
│   ├── RecordLengthError
│   ├── InvalidNumericDataError   ← COBOL S0C7 equivalent
│   ├── FieldOverflowError        ← COBOL size error / truncation
│   └── SignViolationError
└── DataSourceError
    └── SqlError                  (carries sqlcode, sqlstate)
```

### 5.2 Mapping COBOL control flow

| COBOL | Python |
|---|---|
| `READ ... AT END` (e.g. `COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0001.cobol:87`) | Iterator exhaustion: the reader yields records and ends normally. End of file is **not** an exception. |
| `IF SQLCODE NOT = 0` (e.g. `COBOL Programming Course #3 - Advanced Topics/Labs/cbl/CBLDB21.cbl:103`) | Check for SQLCODE 100 (not found / end of cursor), which is normal end of data. Every other non-zero code raises `SqlError`. |
| Abend / `STOP RUN` with non-zero `RETURN-CODE` | Raise; the entry point maps the exception to a non-zero process exit code. |

### 5.3 Rules

- Catch `KeystoneError` subclasses only at the program entry point or at an explicit per-record error boundary. A bare `except:` or `except Exception: pass` MUST NOT be used.
- A per-record error boundary MUST log the error (subject to §4 masking) and count the rejected record. Continuing after a bad record is allowed only if the spec says so. The legacy default is to abend.
- Exit codes: `0` success, `4` warnings, `8` record errors, `12` or higher for a run failure. These match mainframe return-code conventions, so schedulers and JCL condition-code logic keep working.

## 6. Tests

### 6.1 Layout

- Tests live in `tests/` and mirror the package: `src/keystone/records/acct.py` → `tests/records/test_acct.py`.
- Equivalence tests for a ported program live in `tests/programs/test_<programid>.py` with the PROGRAM-ID in lower case, for example `tests/programs/test_cbl0001.py`.

### 6.2 Naming

Test functions MUST be named:

```
test_<unit>_<condition>_<expected_result>
```

Examples:

- `test_acct_record_valid_170_bytes_parses_all_fields`
- `test_acct_record_169_bytes_raises_record_length_error`
- `test_compute_tlimit_without_rounded_truncates_to_cents`
- `test_compute_rounded_half_cent_rounds_away_from_zero`
- `test_cbl0001_sample_input_matches_legacy_output_byte_for_byte`

### 6.3 Required coverage for every port

1. **Golden-file test.** The legacy output for a fixed input, stored under `tests/fixtures/<programid>/`, compared byte for byte.
2. **Rounding and truncation tests.** One test per arithmetic statement that can lose precision, using a half-cent value.
3. **Boundary tests.** Maximum and minimum values for every numeric PIC (e.g. `9999999.99` and `-9999999.99` for `S9(7)V99`), and a value one past each limit.
4. **Bad-data tests.** Invalid packed nibbles and a short record, each asserting the specific `RecordError` subclass.
5. **PII-in-logs test.** Capture log output (`caplog`) and assert that no PII=Yes field value appears.

Test data MUST be synthetic. Real customer data MUST NOT be committed to `tests/`.
