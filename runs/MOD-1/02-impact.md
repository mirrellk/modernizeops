# MOD-1 Impact Analysis: CBL0008 port with OVER-LIMIT flag

Paths: `C2` = `corpus/legacy/COBOL Programming Course #2 - Learning COBOL/Labs`. `CBL0008.cobol` = `C2/cbl/CBL0008.cobol`.
PROGRAM-ID confirmed as CBL0008 (`C2/cbl/CBL0008.cobol:7`). The only JCL that runs it is `CBL0008J` (`C2/jcl/CBL0008J.jcl:12`).
Written against the current brief (`runs/MOD-1/01-brief.json`); this replaces the earlier analysis for the superseded brief.

## Findings

| # | Program | Paragraph | Copybook | Field | Change | Risk | Citation |
|---|---|---|---|---|---|---|---|
| 1 | CBL0008 (Python port) | FD PRINT-LINE / PRINT-REC | PRINT-REC-B.cpy (derived, 62 bytes) | new `FILLER X(02)` at bytes 63-64 of detail line | Add | Medium: record grows 62 to 65; must be spaces | `C2/cbl/CBL0008.cobol:20-29`; `corpus/legacy/copybooks/PRINT-REC-B.cpy:13-21` |
| 2 | CBL0008 (Python port) | FD PRINT-LINE / PRINT-REC | PRINT-REC-B.cpy | new `OVER-LIMIT X(1)` at byte 65 | Add | Medium: new output byte that reveals balance vs limit (PII-adjacent) | `C2/cbl/CBL0008.cobol:20-29` |
| 3 | CBL0008 | WRITE-RECORD | none | `OVER-LIMIT` = 'Y' if `ACCT-BALANCE > ACCT-LIMIT`, else 'N' (equal is 'N') | Modify | Medium: compare packed S9(7)V99 as Decimal; bytes 63-64 spaces | `C2/cbl/CBL0008.cobol:188-193` |
| 4 | CBL0008 | WRITE-HEADERS | none | `HEADER-1..4`, blank line: written FROM 80/83/95/100-byte groups; must be 65 bytes, text unchanged | Modify | Medium: groups are truncated/padded to the record length; non-space content ends at byte 60 or earlier, so nothing is lost at 65 | `C2/cbl/CBL0008.cobol:60-93,131-142` |
| 5 | CBL0008 | WRITE-TLIMIT-TBALANCE | none | `TRAILER-1`, `TRAILER-2` (`TLIMIT-O`, `TBALANCE-O`) written FROM 100-byte groups; must be 65 bytes | Modify | Medium: content ends at byte 60; bytes 61-65 spaces | `C2/cbl/CBL0008.cobol:95-109,153-157` |
| 6 | CBL0008 | LIMIT-BALANCE-TOTAL | none | `TLIMIT`, `TBALANCE` S9(9)V99 COMP-3 | No change in COBOL; reproduce in Python | Low: plain addition, no ROUNDED/SIZE ERROR | `C2/cbl/CBL0008.cobol:49-51,173-176` |
| 7 | CBL0008 | READ-RECORD / FD ACCT-REC | ACCT-FIELDS.cpy (derived) | `ACCT-NO`, `LAST-NAME`, `ACCT-LIMIT`, `ACCT-BALANCE` (+ unused FIRST-NAME, CLIENT-ADDR, RESERVED, COMMENTS) | No change in COBOL; Python parse | Medium: COMP-3 decode, 170-byte record check | `C2/cbl/CBL0008.cobol:31-43,164-167`; `corpus/legacy/copybooks/ACCT-FIELDS.cpy:12-23` |
| 8 | CBL0008 | WRITE-RECORD | PRINT-REC-B.cpy | `ACCT-NO-O`, `LAST-NAME-O`, `ACCT-LIMIT-O`, `ACCT-BALANCE-O` | No change in COBOL; Python formatter | Medium: edited PIC `$$,$$$,$$9.99`, no sign, negatives print unsigned | `C2/cbl/CBL0008.cobol:22-28,189-193` |
| 9 | CBL0008 | WRITE-HEADERS | none | `HDR-YR`, `HDR-MO`, `HDR-DAY` from `FUNCTION CURRENT-DATE` | No change in COBOL; Python reproduces, unmasked in output | Low: only the test comparison masks it | `C2/cbl/CBL0008.cobol:64-73,113-122,132-135` |
| 10 | CBL0008J | RUN step | none | DD `ACCTREC` (`&SYSUID..DATA`), `PRTLINE` (SYSOUT, no LRECL/RECFM) | No change | Low: JCL sets no record length; length comes from the FD only | `C2/jcl/CBL0008J.jcl:12-16` |
| 11 | new Python module | n/a | n/a | port of CBL0008 plus OVER-LIMIT | Add | High: brief risk is high and pii true; output must match legacy bytes | `runs/MOD-1/01-brief.json:45-46` |

Compile uses proc IGYWCL; no TRUNC or ARITH option is coded in the job (`C2/jcl/CBL0008J.jcl:6`).

## Analysis Notes

1. **PRINT-REC is the 62-byte report record and nothing lies beyond byte 62. Confirmed.**
   - `PRINT-REC` items: `ACCT-NO-O` X(8), FILLER X(02), `LAST-NAME-O` X(20), FILLER X(02), `ACCT-LIMIT-O` `$$,$$$,$$9.99` (13), FILLER X(02), `ACCT-BALANCE-O` `$$,$$$,$$9.99` (13), FILLER X(02) (`C2/cbl/CBL0008.cobol:21-29`).
   - 8+2+20+2+13+2+13+2 = 62; this matches Layout B (`corpus/standards/data-dictionary.md:95-99`).
   - The next source line is a comment, then `FD ACCT-REC` (`CBL0008.cobol:30-31`), so no item follows byte 62 and the new bytes 63-65 are appended at the end.
   - Spaces in the FILLERs come from `MOVE SPACES TO PRINT-REC` (`:142`), not from the VALUE clauses (VALUE is not applied to FD records). The new bytes 63-64 must be written as spaces explicitly in Python.

2. **Totals items. Confirmed.**
   - `TLIMIT PIC S9(9)V99 COMP-3 VALUE ZERO` and `TBALANCE PIC S9(9)V99 COMP-3 VALUE ZERO` (`CBL0008.cobol:49-51`): 11 digits, signed, scale 2, 6 bytes each.
   - Accumulated in `LIMIT-BALANCE-TOTAL` (`:173-176`) with `COMPUTE TLIMIT = TLIMIT + ACCT-LIMIT` and `COMPUTE TBALANCE = TBALANCE + ACCT-BALANCE`; no ROUNDED, no ON SIZE ERROR.
   - It is performed once per record inside the loop `PERFORM UNTIL LASTREC = 'Y'`, before `WRITE-RECORD` (`:144-151`). The AT END read (`:164-167`) is never accumulated, so totals cover every record read.

3. **Edited totals items. Confirmed; spelling is `TLIMIT-O` and `TBALANCE-O`.**
   - Both are in `TRAILER-2` (`CBL0008.cobol:102-109`) with `PIC $$$,$$$,$$9.99` (14 characters each).
   - TRAILER-2 layout: FILLER X(22) bytes 1-22, `'Totals ='` bytes 23-30, FILLER X(01) byte 31, `TLIMIT-O` bytes 32-45, FILLER X(01) byte 46, `TBALANCE-O` bytes 47-60, FILLER X(40) bytes 61-100.
   - TRAILER-2 is 22+8+1+14+1+14+40 = 100 bytes before the move into PRINT-REC. TRAILER-1 (`:95-100`) is also 100 bytes (31 spaces, 14 dashes at 32-45, space at 46, 14 dashes at 47-60, 40 spaces).
   - In the legacy 62-byte record these lines are truncated at byte 62 (spaces only). In the Python output they are 60 bytes of content padded with spaces to 65 (AC 7 of the brief).

4. **High-order digit loss on the MOVE. Not triggered on the sample, possible in general.**
   - `MOVE TLIMIT TO TLIMIT-O` and `MOVE TBALANCE TO TBALANCE-O` (`CBL0008.cobol:154-155`).
   - `TLIMIT` holds 9 integer digits. `$$$,$$$,$$9.99` has 9 digit positions but the first `$` is the floating currency symbol only, so it holds at most 8 integer digits (up to 99,999,999.99). A total of 100,000,000.00 or more loses its high-order digit with no error.
   - Sample totals are TLIMIT 47500000.00 and TBALANCE 23004207.47 (`inspect_account_file(C2/data/data)`), 8 integer digits each, so nothing is dropped.
   - Detail fields: `$$,$$$,$$9.99` holds 7 integer digits, the same as `ACCT-LIMIT S9(7)V99`, so no loss there.
   - The Python formatter must reproduce the truncation (drop the high digit) and pin it with a test, per the legacy-defect rule in the cobol-conventions skill.

5. **Run-date characters. Only `HEADER-2` is affected.**
   - `HEADER-2` (`CBL0008.cobol:64-73`) is filled in `WRITE-HEADERS` (`:132-135`) from `FUNCTION CURRENT-DATE` via `WS-CURRENT-DATE-DATA` (`:113-122`).
   - `HEADER-1` (`:60-62`), `HEADER-3` (`:75-83`) and `HEADER-4` (`:85-93`) hold only literals and spaces. Time-of-day fields are not printed.
   - Byte positions in the HEADER-2 line (logical record, no ASA byte, per the brief): `'Year '` 1-5, `HDR-YR` PIC 9(04) 6-9, spaces 10-11, `'Month '` 12-17, `HDR-MO` X(02) 18-19, spaces 20-21, `'Day '` 22-25, `HDR-DAY` X(02) 26-27, spaces 28-83.
   - The test comparison masks bytes 6-9, 18-19 and 26-27 of the second report line only.

6. **WRITE statements and record area. Confirmed.**
   - All writes use `PRINT-REC` (the only 01 under `FD PRINT-LINE`, `CBL0008.cobol:20-21`): `WRITE PRINT-REC FROM HEADER-1` and `FROM HEADER-2` (`:136-137`); `MOVE SPACES TO PRINT-REC` then `WRITE PRINT-REC AFTER ADVANCING 1 LINES` for the blank line (`:138-139`); `FROM HEADER-3` and `FROM HEADER-4` (`:140-141`); `MOVE SPACES TO PRINT-REC` (`:142`); per record `WRITE PRINT-REC` (`:193`); `FROM TRAILER-1` and `FROM TRAILER-2` (`:156-157`).
   - The report is therefore 5 header lines (H1, H2, blank, H3, H4), one detail line per record, and 2 trailer lines: 52 lines for the 45-record sample.
   - `AFTER ADVANCING 1 LINES` is the only carriage-control clause. The brief states the Python output writes no ASA byte and byte positions refer to the logical record, so the blank line is a line of 65 spaces.
   - The detail `WRITE` has no FROM, so it writes whatever is in the record area. The area is cleared at `:142` and only the four edited fields are moved per record, so the FILLERs stay spaces.

7. **Sample ACCTREC file. Answered from the only valid data file.**
   - `inspect_account_file(C2/data/data)`: record_length 170, record_count 45 (7650 bytes), tlimit 47500000.00, tbalance 23004207.47, below 39, equal 0, above 6.
   - 170 bytes matches the ACCT-FIELDS layout that CBL0008 reads (`CBL0008.cobol:32-43`).
   - Records with balance below limit: 39 in total; the tool returns samples 1 (limit 10000.00, balance 188.74), 2 (10000.00, 3188.33), 3 (10000.00, 7008.13).
   - Records with balance above limit: 6 in total; the tool returns samples 5 (10000.00, 31313.13), 6 (10000.00, 31250.33), 35 (1700000.00, 5084035.13).
   - No record has balance equal to limit, so the equal case (AC 4) needs the synthetic test-only record the brief describes.
   - The expected TLIMIT/TBALANCE above can be used as the derived expected values (ticket comment 10007, per the brief). The tool lists at most 3 record numbers per category, so the other 3 "above" and 36 "below" record numbers are not enumerated (Open Question 1, non-blocking; samples suffice for the tests).
   - The other file in the folder, `C2/data/xdata`, is 7088 bytes, not a multiple of 170, and is refused by the tool (`inspect_account_file(C2/data/xdata)`), so it is not the sample.

## Data Mapping

Standards: `corpus/standards/pic-mapping.md` (KFB-STD-002), `corpus/standards/coding-standards.md` (KFB-STD-001).

| COBOL item | PIC | Bytes | Python |
|---|---|---|---|
| `ACCT-NO` | X(8) | 8 | `str` (cp037, right-strip for logic, keep raw bytes); PII, mask to last 4 in logs |
| `ACCT-LIMIT`, `ACCT-BALANCE` | S9(7)V99 COMP-3 | 5 | `Decimal`, scale 2, built from str or int, never float |
| `LAST-NAME` | X(20) | 20 | `str` (cp037); PII, never logged |
| `FIRST-NAME`, `CLIENT-ADDR`, `RESERVED`, `COMMENTS` | X(15), group 60, X(7), X(50) | 15, 60, 7, 50 | not used by the report; keep as raw bytes (170-byte record asserted) |
| `TLIMIT`, `TBALANCE` | S9(9)V99 COMP-3 | 6 | `Decimal`; add with `ROUND_DOWN` context (no ROUNDED); a result beyond 11 digits raises `FieldOverflowError` |
| `ACCT-LIMIT-O`, `ACCT-BALANCE-O` | `$$,$$$,$$9.99` | 13 | `Decimal` to `str` formatter, width 13, no sign, high-order digit dropped beyond 7 integer digits |
| `TLIMIT-O`, `TBALANCE-O` | `$$$,$$$,$$9.99` | 14 | `Decimal` to `str` formatter, width 14, no sign, high-order digit dropped beyond 8 integer digits |
| `ACCT-NO-O`, `LAST-NAME-O` | X(8), X(20) | 8, 20 | `str`, padded to width |
| `FILLER` | X(02) | 2 | spaces, not an attribute |
| `OVER-LIMIT` (new) | X(1) | 1 | `str` of length 1: 'Y' if `balance > limit`, else 'N' (Decimal comparison) |
| 63-64 (new spacer) | X(02) | 2 | two spaces |
| `HDR-YR`, `HDR-MO`, `HDR-DAY` | 9(04), X(02), X(02) | 4, 2, 2 | `str` from the current date; not masked in module output |
| `LASTREC` | X | 1 | not an attribute; iterator exhaustion (AT END) |
| `PRINT-REC` | group | 62 legacy, 65 Python | frozen pydantic model for the 65-byte line with a length assert; header and trailer lines are padded with spaces to 65 |

## Open Questions

None blocking.

1. (non-blocking) Complete record-number lists for the OVER-LIMIT tests. `inspect_account_file` returns only 3 sample records per category, so 3 of the 6 "above" records and 36 of the 39 "below" records are not enumerated. The tests can use records 1, 2, 3 (below) and 5, 6, 35 (above); the test code may derive the full lists from the file.
2. (non-blocking) The ticket text was not provided to me, so I identified the sample ACCTREC file as `C2/data/data` because it is the only file under the data folder that decodes as 170-byte ACCT-FIELDS records. Confirm this is the file the ticket means.
3. (non-blocking) Target module name and location are not in the brief. I assume `src/keystone/programs/` with `tests/programs/test_cbl0008.py`, per the cobol-conventions skill.
