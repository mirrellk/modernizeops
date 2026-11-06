# Keystone Federal Bank: COBOL PIC/USAGE to Python Type Mapping

| | |
|---|---|
| Document ID | KFB-STD-002 |
| Applies to | Field decoding and encoding in `src/keystone/records/` |
| Related | `coding-standards.md` §2–§3, `data-dictionary.md` |

Keystone Federal Bank is a fictional institution. "Corpus example" citations are `file:line` relative to `corpus/legacy/`. A `—` means the form does not appear in the corpus and is listed for completeness.

Path abbreviations used below:

- `C2/` = `COBOL Programming Course #2 - Learning COBOL/Labs/cbl/`
- `C3/` = `COBOL Programming Course #3 - Advanced Topics/Labs/cbl/`

## 1. Core mapping table

`n` = digit or character count, `d` = digits after `V`.

| COBOL clause | Storage | Bytes | Python type | Decode (read) | Encode (write) | Corpus example |
|---|---|---|---|---|---|---|
| `PIC X(n)` | Characters (EBCDIC) | `n` | `str` | `raw.decode("cp037")`; right-strip spaces for logic | left-justify, pad with spaces to `n`, `.encode("cp037")`; too long raises `FieldOverflowError` | `ACCT-NO PIC X(8)`: `C2/CBL0001.cobol:43` |
| `PIC 9(n)` (USAGE DISPLAY) | Zoned decimal, unsigned | `n` | `int` | each byte must be EBCDIC `F0`–`F9`; otherwise `InvalidNumericDataError` | zero-pad left to `n` digits; negative raises `SignViolationError` | `PRT-REC PIC 9(05)`: `C2/COBOL.cobol:19` |
| `PIC S9(n)` (USAGE DISPLAY) | Zoned decimal, sign in zone of **last** byte | `n` | `int` | last byte zone `C`/`F` = +, `D` = −; digit nibbles 0–9 | zone `C` for +, `D` for − on last byte | — (S9 appears only with `V` or `COMP` in FDs) |
| `PIC 9(n)V9(d)` | Zoned decimal, implied point, unsigned | `n+d` | `Decimal` | as `9(n+d)`, then `Decimal(int_value).scaleb(-d)` | `value.scaleb(d)` must be an integral value, then encode as `9(n+d)` | `9(7)V99` (WORKING-STORAGE only, 4 occurrences) |
| `PIC S9(n)V9(d)` (DISPLAY) | Zoned decimal, implied point, signed | `n+d` | `Decimal` | as `S9(n+d)`, then `scaleb(-d)` | quantize to `d` places first (see coding-standards §2.3) | `ACCT-LIMIT PIC S9(7)V99`: `C2/CBL0010.cobol:34` |
| `V` (implied decimal point) | **No storage**: position only | 0 | (scale of the `Decimal`) | apply `scaleb(-d)` | quantize to `Decimal(1).scaleb(-d)` | in all `V99` fields |
| `PIC S9(n)V9(d) COMP-3` / `PACKED-DECIMAL` | Packed BCD, two digits per byte, sign in low nibble of last byte | `(n+d)//2 + 1` | `Decimal` | see §2.1 | see §2.1 | `ACCT-LIMIT PIC S9(7)V99 COMP-3`: `C2/CBL0001.cobol:44` (5 bytes) |
| `PIC S9(n) COMP` / `BINARY` / `COMP-4` | Big-endian two's-complement binary | 1–4 → 2; 5–9 → 4; 10–18 → 8 | `int` | `int.from_bytes(raw, "big", signed=True)` | `.to_bytes(size, "big", signed=True)`; check that the value fits `n` digits (see §2.2) | `TABLE-VAR PIC S9(4) COMP`: `C2/SRCHBIN.cobol:26` (2 bytes) |
| `PIC 9(n) COMP` (unsigned) | Big-endian unsigned binary | as above | `int` | `signed=False` | `signed=False` | — |
| `COMP-5` | Native binary, **no** PIC digit limit | as `COMP` | `int` | as `COMP` | range limited by byte size, not PIC | — |
| `COMP-1` / `COMP-2` | IBM hexadecimal floating point (not IEEE 754) | 4 / 8 | `float` (**never money**) | needs an IBM HFP converter; `struct` is wrong | IBM HFP encoder | — |

## 2. Encoding details

### 2.1 Packed decimal (`COMP-3`)

Layout of `S9(7)V99 COMP-3` (9 digits, 5 bytes): `d1d2 d3d4 d5d6 d7d8 d9s`

- Each nibble except the last holds one decimal digit (0–9). The last nibble is the sign: `C` = positive, `D` = negative, `F` = unsigned/positive. Any other sign nibble, or a digit nibble above 9, MUST raise `InvalidNumericDataError` (the COBOL S0C7 data exception).
- An even digit count gets a leading zero nibble. Byte length is always `digits // 2 + 1`.
- On write, use sign `C` for positive or zero and `D` for negative, unless the field is unsigned (`9` without `S`), which uses `F`.

```python
def unpack_comp3(raw: bytes, scale: int) -> Decimal:
    nibbles = "".join(f"{b:02X}" for b in raw)
    digits, sign = nibbles[:-1], nibbles[-1]
    if not digits.isdigit() or sign not in "CDF":
        raise InvalidNumericDataError(raw.hex())
    value = Decimal(int(digits)).scaleb(-scale)
    return -value if sign == "D" else value
```

### 2.2 Binary (`COMP`) truncation

With the Enterprise COBOL default `TRUNC(STD)`, a `COMP` field is limited to its PIC digit count, not its byte size. For example, `S9(4) COMP` holds −9999 to 9999, even though 2 bytes could hold up to 32767. Ports MUST enforce the PIC limit unless the program was compiled with `TRUNC(BIN)`. Record the compile option in the port's spec.

### 2.3 Zoned sign overpunch (ASCII transfers)

If a dataset was converted to ASCII with a text transfer, signed zoned fields arrive with the sign "overpunched" into the last character: `{ A–I` = +0 to +9, `} J–R` = −0 to −9. Readers for ASCII-transferred files MUST decode this convention explicitly. Packed and binary fields are corrupted by text transfers, so those datasets MUST be transferred in binary.

## 3. Edited (report) PICs

Edited PICs are **output-only** display formats. They are never parsed back into business values. In Python they map to a `Decimal → str` formatter whose output is exactly the PIC length.

| Edited PIC | Length | Meaning | Python formatting rule | Corpus example |
|---|---|---|---|---|
| `$$,$$$,$$9.99` | 13 | Floating `$`: one `$` printed directly left of the first significant digit; commas suppressed inside leading blanks; last integer digit always shown | `f"${abs(v):,.2f}".rjust(13)`, then verify length = 13; values over 9,999,999.99 raise `FieldOverflowError`. No sign position, so negatives print **without** a sign (match legacy; flag in spec). | `ACCT-LIMIT-O`: `C2/CBL0001.cobol:30` |
| `$$$,$$$,$$9.99` | 14 | As above, one more digit position | `f"${abs(v):,.2f}".rjust(14)` | used in WORKING-STORAGE totals (10 occurrences) |
| `ZZ,ZZZ,ZZ9.99` | 13 | Leading zeros replaced by spaces, commas suppressed inside the blanks, no currency sign | `f"{abs(v):,.2f}".rjust(13)` | `ACCT-LIMIT-O`: `C2/CBL0005.cobol:36` |
| `Z` | 1 per `Z` | Zero suppression → space | right-justify, space-pad | in `ZZ,ZZZ,ZZ9.99` |
| `9` (in edited PIC) | 1 | Always prints a digit | — | the `9` before `.99` |
| `.` (actual point) | 1 | Printed decimal point; unlike `V`, it takes a byte | part of the `.2f` format | all of the above |
| `,` | 1 | Printed comma; becomes a space when it falls in the suppressed region | Python `,` grouping, then `rjust` (Python omits commas in leading blanks, which matches COBOL) | all of the above |
| `-` / `+` / `CR` / `DB` | 1 / 1 / 2 / 2 | Sign display | must be added explicitly; not in the corpus | — |
| `*` | 1 | Check-protect: leading zeros become `*` | replace leading spaces with `*` | — |
| `B` / `0` / `/` | 1 | Inserted space / zero / slash | positional insert | — |

Every edited-PIC formatter MUST have a golden test against the real COBOL output for: zero, a value with one significant digit, a value that fills every digit position, and a negative value.

## 4. Group items, `FILLER`, `OCCURS` and level-88

| COBOL construct | Python representation | Corpus example |
|---|---|---|
| Group item (level number with children, no PIC), e.g. `05 CLIENT-ADDR.` | Nested frozen `pydantic` model; its bytes are the concatenation of its children | `CLIENT-ADDR`: `C2/CBL0001.cobol:50` |
| Group or record redefined as one `PIC X(n)` | `bytes`/`str` at the FD level, with the structured view defined separately and applied explicitly | `ACCT-FIELDS PIC X(170)`: `C2/SRCHBIN.cobol:20` |
| `FILLER` | Not a model attribute. Kept in the layout spec as an anonymous span so offsets stay correct; written back as spaces | `FILLER PIC X(02)`: `C2/CBL0004.cobol:26` |
| `RESERVED` (a named filler) | Read and preserved as raw bytes; never interpreted | `RESERVED PIC X(7)`: `C2/CBL0001.cobol:54` |
| `OCCURS n TIMES` | `tuple[Model, ...]` of fixed length `n` | `ACCT-TABLE-ITEM OCCURS 45 TIMES`: `C2/SRCHBIN.cobol:30` |
| `88 name VALUE 'x'.` (condition name) | Read-only `bool` property, or an `enum.Enum` when there are several values on the same field | `88 STATE VALUE 'Virginia'`: `C2/CBL0007.cobol:42` |

## 5. DB2 column types (embedded SQL)

For programs that read DB2 through `EXEC SQL`, map the declared column type, not the host variable's PIC:

| DB2 type | Python type | Corpus example |
|---|---|---|
| `CHAR(n)` | `str` (right-strip) | `ACCTNO CHAR(8) NOT NULL`: `C3/CBLDB21.cbl:54` |
| `DECIMAL(p,s)` | `Decimal` quantized to `s` places | `LIMIT DECIMAL(9,2)`: `C3/CBLDB21.cbl:55` |
| nullable column (no `NOT NULL`) | `Decimal \| None`; `None` must be handled explicitly, never coerced to 0 | `LIMIT`, `BALANCE`: `C3/CBLDB21.cbl:55-56` |
