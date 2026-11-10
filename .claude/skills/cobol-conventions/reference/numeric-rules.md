# Numeric rules: COMP-3, ROUNDED, size errors, signs

Condensed from `corpus/standards/coding-standards.md` §2 (KFB-STD-001) and
`corpus/standards/pic-mapping.md` §2 (KFB-STD-002). Those documents are authoritative; cite them.
Corpus citations are `file:line` relative to `corpus/legacy/`, with
`C2/` = `COBOL Programming Course #2 - Learning COBOL/Labs/cbl/`.

## Contents

1. Decimal context
2. ROUNDED vs truncation
3. Size errors (overflow)
4. Signs
5. COMP-3 packed decimal
6. COMP binary truncation
7. Zoned sign overpunch (ASCII transfers)

---

## 1. Decimal context

Every module that does money arithmetic sets an explicit context; never rely on the global default.

```python
from decimal import (
    ROUND_HALF_UP, Context, Decimal, DivisionByZero, InvalidOperation, Overflow,
)

KFB_CONTEXT = Context(prec=31, rounding=ROUND_HALF_UP,
                      traps=[InvalidOperation, DivisionByZero, Overflow])
```

`prec=31` covers the largest fixed-point intermediate Enterprise COBOL produces (`ARITH(EXTEND)`).
A different value must be documented. Build `Decimal` from `str` or `int` only:
`Decimal("19.99")`, never `Decimal(19.99)`.

## 2. ROUNDED vs truncation

COBOL rounds only when the statement says `ROUNDED`; otherwise it **truncates toward zero**.

| COBOL statement | Python |
|---|---|
| `COMPUTE X ROUNDED = expr` | `expr.quantize(SCALE, rounding=ROUND_HALF_UP)` |
| `COMPUTE X = expr` (no `ROUNDED`) | `expr.quantize(SCALE, rounding=ROUND_DOWN)` |
| `ADD` / `SUBTRACT` / `MULTIPLY` / `DIVIDE ... GIVING X ROUNDED` | same as `ROUNDED` row |
| any of the above without `ROUNDED` | same as truncation row |

- `SCALE = Decimal(1).scaleb(-n)`, `n` = digits after `V` in the **receiving** field
  (`Decimal("0.01")` for `V99`).
- `ROUND_HALF_UP` rounds halves away from zero: `2.345 → 2.35`, `-2.345 → -2.35`. This matches
  COBOL `ROUNDED` in default mode.
- Do **not** use `ROUND_HALF_EVEN` (the `Decimal` default) unless the source says
  `ROUNDED MODE NEAREST-EVEN`.
- Round once, at assignment. COBOL keeps intermediates at full precision.

**Corpus note:** no program in `corpus/legacy` uses `ROUNDED`. Every statement, e.g.
`COMPUTE TLIMIT = TLIMIT + ACCT-LIMIT` (`C2/CBL0010.cobol:173`), truncates. Ports of these programs
use `ROUND_DOWN`.

```python
CENTS = Decimal("0.01")

def assign_v99(value: Decimal, *, rounded: bool) -> Decimal:
    mode = ROUND_HALF_UP if rounded else ROUND_DOWN
    return value.quantize(CENTS, rounding=mode, context=KFB_CONTEXT)
```

Test with a half-cent value for every statement that can lose precision, e.g.
`test_compute_tlimit_without_rounded_truncates_to_cents`.

## 3. Size errors (overflow)

COBOL silently drops high-order digits when a result doesn't fit the receiving PIC, unless
`ON SIZE ERROR` is coded. No corpus program codes it. Ports must:

1. Check the quantized result fits the receiving digit count (`S9(7)V99` → at most 7 integer
   digits, i.e. `abs(v) <= Decimal("9999999.99")`).
2. Raise `FieldOverflowError` instead of truncating.
3. Include a test that documents the legacy truncation, so the behavior change is visible and
   approved.

## 4. Signs

- Unsigned PIC (`9(7)V99`) stores the absolute value; COBOL drops a negative sign on assignment.
  Ports raise `SignViolationError` unless the spec says the drop is intentional.
- Edited PICs without a sign position (`$$,$$$,$$9.99`) print negatives **without** a sign. Match
  legacy and flag it in the spec.

## 5. COMP-3 packed decimal

Layout of `S9(7)V99 COMP-3` (9 digits, 5 bytes): `d1d2 d3d4 d5d6 d7d8 d9s`
Corpus example: `ACCT-LIMIT PIC S9(7)V99 COMP-3` (`C2/CBL0001.cobol:44`).

- Two digits per byte; the last nibble is the sign: `C` = +, `D` = −, `F` = unsigned/+.
- Byte length = `digits // 2 + 1`. An even digit count gets a leading zero nibble.
- Any other sign nibble, or a digit nibble > 9, raises `InvalidNumericDataError` (S0C7).
- On write: `C` for positive or zero, `D` for negative; unsigned fields (`9` without `S`) use `F`.
- Never pass packed bytes through `cp037` or any codepage; text-mode transfers corrupt them.

```python
def unpack_comp3(raw: bytes, scale: int) -> Decimal:
    nibbles = "".join(f"{b:02X}" for b in raw)
    digits, sign = nibbles[:-1], nibbles[-1]
    if not digits.isdigit() or sign not in "CDF":
        raise InvalidNumericDataError(raw.hex())
    value = Decimal(int(digits)).scaleb(-scale)
    return -value if sign == "D" else value


def pack_comp3(value: Decimal, digits: int, scale: int, *, signed: bool = True) -> bytes:
    if not signed and value < 0:
        raise SignViolationError(str(value))
    unscaled = value.scaleb(scale)
    if unscaled != unscaled.to_integral_value():
        raise ValueError("quantize to the field scale before packing")
    text = str(abs(int(unscaled)))
    if len(text) > digits:
        raise FieldOverflowError(str(value))
    sign = ("D" if value < 0 else "C") if signed else "F"
    nibbles = text.rjust(digits, "0") + sign
    if len(nibbles) % 2:
        nibbles = "0" + nibbles
    return bytes.fromhex(nibbles)
```

Bad-data tests: an invalid sign nibble (e.g. `0x...A`) and a digit nibble of `A`-`F`, each asserting
`InvalidNumericDataError`.

## 6. COMP binary truncation

Under the default `TRUNC(STD)`, a `COMP` field is limited to its PIC digit count, not its byte
size: `S9(4) COMP` holds −9999..9999 although 2 bytes could hold 32767
(`TABLE-VAR PIC S9(4) COMP`, `C2/SRCHBIN.cobol:26`). Enforce the PIC limit unless the program was
compiled with `TRUNC(BIN)`, and record the compile option in the port's spec. `COMP-5` is limited
by byte size only.

## 7. Zoned sign overpunch (ASCII transfers)

If a dataset was text-transferred to ASCII, signed zoned fields carry the sign in the last
character: `{ A-I` = +0..+9, `} J-R` = −0..−9. Readers for such files decode this explicitly.
Packed and binary fields are corrupted by text transfers; those datasets must move in binary.
