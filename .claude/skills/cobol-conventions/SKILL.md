---
name: cobol-conventions
description: How to read Keystone Federal Bank COBOL (programs, FDs, derived copybooks, JCL) and map it to Python 3.12 with byte-for-byte equivalence. Use when reading COBOL/copybooks or writing Python that replaces them - including PIC/USAGE decoding, COMP-3 packed decimal, ROUNDED vs truncation, edited report PICs, record layouts, Decimal money handling, and PII-safe logging. Use it even when the user just says "port", "look at CBL00xx", "what does this field hold", or asks for a record parser, report formatter or test for a legacy program.
---

# Keystone COBOL conventions

The goal of every port is **behavioral equivalence**: the Python program produces the same output
bytes as the COBOL program for the same input. Legacy defects are reproduced first, pinned by a
test, and fixed only in a separate, named change. Everything below serves that goal.

Authoritative sources (cite these, not this skill, in design docs):

- `corpus/standards/coding-standards.md` (KFB-STD-001): money, rounding, parsing, logging, errors, tests
- `corpus/standards/pic-mapping.md` (KFB-STD-002): PIC/USAGE → Python types
- `corpus/standards/data-dictionary.md` (KFB-STD-003): every FD field, offsets, PII flags
- `corpus/legacy/INVENTORY.md`: program → files, DD names, copybooks

## Bundled references - read when needed

| File | Read it when |
|---|---|
| `reference/pic-mapping.md` | Decoding/encoding any field, sizing a record, formatting an edited PIC, mapping DB2 columns |
| `reference/numeric-rules.md` | Any arithmetic, `COMP-3`, `ROUNDED`, size errors, signs, `COMP` truncation |

## Reading a program

1. **Find it.** Use the `kb` MCP server: `list_programs` for the inventory, `search_kb` to locate
   code, then `get_source` to read the exact lines before citing `path:start-end`. Never cite a line
   you have not read.
2. **Check the PROGRAM-ID, not just the file name.** `CBLC1.cobol` declares `PROGRAM-ID. CBL0006`.
3. **Read the FD, then the data dictionary entry.** Most programs repeat a shared layout inline; the
   derived copybooks in `corpus/legacy/copybooks/` are extracted from those (no program `COPY`s
   them). Confirm the program matches the copybook - known variants:
   - `CBL0010`: `ACCT-LIMIT PIC S9(7)V99` **without** `COMP-3` → 174-byte record, misreads a
     170-byte file. A legacy defect; reproduce it, don't silently "fix" it.
   - `CBL0007`: adds `88 STATE VALUE 'Virginia'` (no storage).
   - `SRCHBIN`/`SRCHSER`: record is one `PIC X(170)`; structure applied in WORKING-STORAGE.
4. **Trace the PROCEDURE DIVISION.** Note every `MOVE`, `COMPUTE`/`ADD`/`SUBTRACT`, whether
   `ROUNDED` or `ON SIZE ERROR` is coded, `READ ... AT END`, and SQLCODE checks.
5. **Check the JCL** for DD names, record lengths and compile options (`TRUNC`, `ARITH`).

COBOL source layout reminders: columns 1-6 sequence, column 7 indicator (`*` or `/` = comment,
`-` = continuation), code in 8-72, 73-80 ignored. Level `01` = record, `05`/`10` = children,
`88` = condition name, `FILLER` = anonymous span.

## Mapping to Python - the essentials

Full table in `reference/pic-mapping.md`. The rules that cause most bugs:

| COBOL | Python | Watch out for |
|---|---|---|
| `PIC X(n)` | `str` via `cp037` | right-strip for logic; keep raw bytes if written back; pad on write; overflow raises |
| `PIC 9(n)` / `S9(n)` DISPLAY | `int` | zoned; sign in zone of **last** byte |
| any PIC with `V` | `Decimal` | `V` takes no storage; scale = digits after `V` |
| `COMP-3` | `Decimal` | `(digits // 2) + 1` bytes; never codepage-decode |
| `COMP` / `BINARY` | `int` | big-endian; limited to PIC digits under `TRUNC(STD)` |
| `COMP-1`/`COMP-2` | `float` | IBM HFP, not IEEE; **never money** |
| Edited PIC (`$$,$$$,$$9.99`) | `Decimal → str` formatter | output only; exact length; negatives print without sign |
| group item | frozen `pydantic` model | bytes = concatenation of children |
| `OCCURS n` | `tuple[Model, ...]` length `n` | |
| `88` level | `bool` property / `Enum` | |
| `FILLER` / `RESERVED` | not an attribute / raw bytes | preserved so offsets and output stay exact |
| DB2 `DECIMAL(p,s)` nullable | `Decimal \| None` | never coerce `None` to 0 |

## Money and arithmetic - non-negotiable

- Money and any `V` field is `decimal.Decimal`, built from `str` or `int`, never `float`.
- Use a module-level `KFB_CONTEXT` (`prec=31`, `ROUND_HALF_UP`, traps on `InvalidOperation`,
  `DivisionByZero`, `Overflow`).
- **No `ROUNDED` → truncate (`ROUND_DOWN`).** `ROUNDED` → `ROUND_HALF_UP`. Never the `Decimal`
  default `ROUND_HALF_EVEN`. No corpus program uses `ROUNDED`, so ports here truncate.
- Round once, at assignment to the receiving field. Keep intermediates at full precision.
- A result too large for the receiving PIC raises `FieldOverflowError` (COBOL truncates silently);
  a negative into an unsigned PIC raises `SignViolationError`. Both need a test showing the legacy
  behavior so the change is visible.

Details and code: `reference/numeric-rules.md`.

## Records and I/O

- One layout definition per record in `src/keystone/records/`, with offsets from the data
  dictionary. Assert total length; wrong length raises `RecordLengthError`.
- Open files `rb`. Slice bytes first, decode per field. Packed/binary bytes are not characters.
- Writers rebuild the full record, including `FILLER` and `RESERVED`, to the exact length.
- Invalid zoned/packed data raises `InvalidNumericDataError` with record number and field name
  (the S0C7 equivalent). Never return 0 or skip silently.
- `AT END` = normal iterator exhaustion. SQLCODE 100 = normal end; other non-zero → `SqlError`.
- Errors derive from `keystone.errors.KeystoneError`. Exit codes: 0 ok, 4 warn, 8 record errors,
  12+ run failure.

## PII and logging

- Use `keystone.logging.get_logger(__name__)`; no `print()` for diagnostics. JSON logs with
  `timestamp`, `level`, `program`, `run_id`, `event`, `record_no`.
- Check the **PII** column in the data dictionary for every field you touch. `Yes` → mask account
  numbers to last 4 (`****1809`), omit names and addresses. `Possible` (e.g. `COMMENTS`) → omit.
- Balances and limits are PII next to an account number; log amounts only at `DEBUG`, never beside
  an unmasked account number.
- Test data is synthetic only.

## Tests every port needs

Tests mirror the package (`tests/records/test_acct.py`, `tests/programs/test_cbl0001.py`), named
`test_<unit>_<condition>_<expected_result>`:

1. Golden file vs legacy output, byte for byte (`tests/fixtures/<programid>/`).
2. One rounding/truncation test per arithmetic statement, using a half-cent value.
3. Boundary values for every numeric PIC, plus one past each limit.
4. Bad data: invalid packed nibble and short record, asserting the specific `RecordError`.
5. PII-in-logs test with `caplog`.
6. Edited-PIC formatters: zero, one significant digit, all positions filled, negative.

## When something is unclear

If the source, the standards and the data dictionary don't settle a behavior (sign handling, a
missing compile option, which layout a file really uses), record it as an open question in the
run's output under `runs/<CR-KEY>/` and stop. Do not invent a business rule.
