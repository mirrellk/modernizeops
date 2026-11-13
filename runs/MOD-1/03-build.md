# MOD-1 Build Record: CBL0008 port with OVER-LIMIT flag

## Files Changed

- `src/keystone/programs/cbl0008.py` (new): CBL0008 port. COMP-3 parsing, 170-byte record check, truncating totals, edited PIC formatters, 65-byte detail model with OVER-LIMIT, header/trailer lines, report writer.
- `src/keystone/programs/__init__.py` (new): package marker.
- `src/keystone/errors.py` (new): `KeystoneError`, `RecordError`, `RecordLengthError`, `InvalidNumericDataError`, `FieldOverflowError` (required by the conventions skill; did not exist).
- `tests/programs/test_cbl0008.py` (new): tests below.

## Tests

All in `tests/programs/test_cbl0008.py`.

| Test | Criterion |
|---|---|
| test_totals_sample_tlimit_equals_sum_and_printed_value | AC1 |
| test_totals_sample_tbalance_equals_sum_and_printed_value | AC2 |
| test_over_limit_balance_above_limit_is_y; test_over_limit_sample_flags_match_independent_comparison | AC3 |
| test_over_limit_balance_equal_limit_is_n | AC4 (synthetic, test-only) |
| test_over_limit_balance_below_limit_is_n; test_over_limit_negative_balance_is_n | AC5 |
| test_detail_line_length_65_with_spaces_then_flag | AC6 |
| test_every_print_line_is_65_bytes; test_header_trailer_lines_padded_with_spaces_on_right | AC7 |
| test_headers_text_unchanged_and_no_over_limit_heading | AC8 |
| test_output_file_has_no_asa_byte_and_fixed_65_byte_records | AC9 |
| test_report_matches_legacy_layout_except_new_bytes_padding_and_run_date | AC10 |
| test_run_date_is_not_masked_in_module_output | AC11 |
| edit_detail_amount / edit_total_amount parametrized tests, add_to_total half-cent and overflow tests, parse_record boundary/invalid nibble/length tests, read_records partial record test, PII log test | Standards (non-criterion) |

## Test Run

- `uv run pytest -q`: 219 passed in 3.73s (31 in the new file).
- `uv run ruff check .`: All checks passed.

## Deviations and Open Questions

1. Process deviation: I wrote the implementation before the tests, so the "confirm tests fail first" step was not done. The first run found one failure, which was a test bug (my expected HEADER-3 string and an "OVER" substring check that matched a last name); I fixed the tests, not the criteria.
2. There is no real CBL0008 output in the corpus. AC10 compares to a legacy layout rebuilt independently in the test (f-string formatting and raw byte decoding) and one hand-checked record, not a mainframe golden file.
3. Output encoding and record framing are not stated in the brief. `write_report` writes cp037 fixed 65-byte records with no newline (per the conventions skill). The in-memory `Report.lines` are plain str. Non-blocking; confirm if a different file format is wanted.
4. No logging is emitted by the module (not requested); `get_logger` does not exist in src. The PII test only asserts that nothing is logged.
5. Run date comes from `datetime.now()` (local) by default, or the `run_date` argument; mirrors `FUNCTION CURRENT-DATE`.
6. Impact open questions 1 to 3 (full record-number lists, sample file identity `C2/data/data`, module location) are carried over unchanged; tests derive record lists from the file and use `src/keystone/programs/`.
7. Edited-PIC high-order truncation (total of 100,000,000.00 or more prints without its high digit) is reproduced as a legacy defect and pinned by a test.

## Revision 1

Fixes for runs/MOD-1/04-review.json, using the decision in runs/MOD-1/04-decision-1.md.

### Files Changed (revision 1)

- `src/keystone/records/__init__.py`, `src/keystone/records/acct.py` (new): single ACCT-FIELDS layout (170 bytes, all fields, offsets from KFB-STD-003), `parse_acct`, `to_bytes`; PII fields hidden from repr. Replaces the inline layout in the program (minor 4).
- `src/keystone/records/packed.py` (new): `decode_comp3`, now accepting sign nibbles A, C, E, F (positive) and B, D (negative) (minor 2).
- `src/keystone/logging.py` (new): `get_logger`, `JsonFormatter` (timestamp, level, program, run_id, event, record_no), `mask_account` (minor 3).
- `src/keystone/programs/cbl0008.py`: uses the records module; logs run_start, per-record DEBUG (record number and masked account only) and run_end with record counts.
- `tests/programs/test_cbl0008.py`: AC10 test and logging tests reworked; new tests below.

### Tests (revision 1)

| Test | Covers |
|---|---|
| test_report_matches_legacy_layout_except_new_bytes_padding_and_run_date | AC10, major: now compares encoded cp037 bytes of the file the module wrote against a reference rebuilt from CBL0008.cobol:60-109; docstring cites decision 04-decision-1.md (Jira MOD-1 comment 10009) |
| test_run_logs_no_account_numbers_or_names | PII: asserts logs exist, contain only masked accounts, no names or amounts |
| test_json_formatter_emits_required_fields_and_masks_account | logging standard |
| test_decode_comp3_accepts_all_ibm_sign_nibbles; test_decode_comp3_invalid_sign_nibble_raises | minor 2 |
| test_acct_fields_layout_roundtrips_170_bytes_and_hides_pii_in_repr | minor 4 |
| test_parse_record_invalid_packed_nibble_raises_with_record_and_field | changed: sign nibble 0x1A is now valid (A), test uses 0x15 |

### Test Run (revision 1)

- `uv run pytest -q`: 228 passed.
- `uv run ruff check .`: All checks passed.

### Deviations and Open Questions (revision 1)

1. AC10 remains verified against a source-derived reference, not a mainframe capture, by explicit business decision. A real golden file, if captured, replaces it.
2. The log "event" field carries the masked account for record events (the formatter emits only the six standard fields). No amounts or names are logged.
3. Superseded: open item 4 above (no logging) is resolved.
