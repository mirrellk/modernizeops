# Legacy Program Inventory

Source: the Open Mainframe Project COBOL Programming Course (see `LICENSE`).
This file has one row per COBOL program, built from the code itself (comment lines in column 7 are ignored):

- **PROGRAM-ID**: from the `IDENTIFICATION DIVISION`.
- **Files read/written**: each `SELECT … ASSIGN TO` gives the internal file name and its DD name. The mode comes from the `OPEN` statements: R = `INPUT`, W = `OUTPUT`, RW = `I-O`. DB2 tables come from `EXEC SQL` cursors and statements. Plain `ACCEPT` reads from SYSIN.
- **Copybooks**: `COPY` statements, `EXEC SQL INCLUDE` members, and *derived* copybooks. A derived copybook in `copybooks/` was extracted by ModernizeOps from an FD record coded identically inline in the program; the program itself does not `COPY` it and is unchanged.

Notes:
- No program uses a `COPY` statement; the original course has no copybooks. The only include is `SQLCA`, which is DB2's built-in SQL communication area.
- Derived copybooks (one per FD record layout repeated verbatim in two or more programs):
  - `copybooks/ACCT-FIELDS.cpy`: `ACCT-FIELDS` (170 bytes), FD `ACCT-REC`, 14 programs
  - `copybooks/PRINT-REC-B.cpy`: `PRINT-REC` (62 bytes), FD `PRINT-LINE`, 12 programs
  - `copybooks/PRINT-REC-A.cpy`: `PRINT-REC` (119 bytes), FD `PRINT-LINE`, 3 programs
  - `copybooks/REPREC.cpy`: `REPREC` (119 bytes), FD `REPOUT`, 2 programs
- Not extracted: `CBL0007` (adds `88 STATE`) and `CBL0010` (`ACCT-LIMIT` without `COMP-3`) differ from `ACCT-FIELDS.cpy`; `CBL0005`'s `PRINT-REC` uses `ZZ` editing; `SRCHBIN` and `SRCHSER` declare `ACCT-FIELDS` as one undivided `PIC X(170)`; all other records occur in a single program.
- `CBLC1.cobol` declares `PROGRAM-ID. CBL0006`, the same name as `CBL0006.cobol`.
- `Z#####T` is the course's placeholder DB2 table name (learners replace `#####` with their user ID).
- `DISPLAY` output to SYSOUT is not listed.

| PROGRAM-ID | Source | Files read/written | Copybooks |
|---|---|---|---|
| ADDAMT | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/ADDAMT.cobol | SYSIN via `ACCEPT` (R) | — |
| CBL0001 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0001.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | `copybooks/ACCT-FIELDS.cpy` (derived), `copybooks/PRINT-REC-A.cpy` (derived) |
| CBL0002 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0002.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | `copybooks/ACCT-FIELDS.cpy` (derived), `copybooks/PRINT-REC-A.cpy` (derived) |
| CBL0004 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0004.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | `copybooks/ACCT-FIELDS.cpy` (derived), `copybooks/PRINT-REC-B.cpy` (derived) |
| CBL0005 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0005.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | `copybooks/ACCT-FIELDS.cpy` (derived) |
| CBL0006 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0006.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | `copybooks/ACCT-FIELDS.cpy` (derived), `copybooks/PRINT-REC-B.cpy` (derived) |
| CBL0007 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0007.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | `copybooks/PRINT-REC-B.cpy` (derived) |
| CBL0008 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0008.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | `copybooks/ACCT-FIELDS.cpy` (derived), `copybooks/PRINT-REC-B.cpy` (derived) |
| CBL0009 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0009.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | `copybooks/ACCT-FIELDS.cpy` (derived), `copybooks/PRINT-REC-B.cpy` (derived) |
| CBL0010 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0010.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | `copybooks/PRINT-REC-B.cpy` (derived) |
| CBL0011 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0011.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | `copybooks/ACCT-FIELDS.cpy` (derived), `copybooks/PRINT-REC-B.cpy` (derived) |
| CBL0012 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0012.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | `copybooks/ACCT-FIELDS.cpy` (derived), `copybooks/PRINT-REC-B.cpy` (derived) |
| CBL0013 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0013.cobol | — | — |
| CBL0014 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0014.cobol | — | — |
| CBL0015 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0015.cobol | — | — |
| CBL0033 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0033.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | `copybooks/ACCT-FIELDS.cpy` (derived), `copybooks/PRINT-REC-A.cpy` (derived) |
| CBL006A | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL006A.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | `copybooks/ACCT-FIELDS.cpy` (derived), `copybooks/PRINT-REC-B.cpy` (derived) |
| CBL0006 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBLC1.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | `copybooks/ACCT-FIELDS.cpy` (derived), `copybooks/PRINT-REC-B.cpy` (derived) |
| CBLC2 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBLC2.cobol | — | — |
| COBOL | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/COBOL.cobol | `PRT-LINE` → DD `PRTLINE` (W)<br>`PRT-DONE` → DD `PRTDONE` (W) | — |
| HELLO | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/HELLO.cobol | — | — |
| PAYROL00 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/PAYROL00.cobol | — | — |
| PAYROL0X | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/PAYROL0X.cobol | — | — |
| SRCHBIN | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/SRCHBIN.cobol | `ACCT-REC` → DD `ACCTREC` (R) | — |
| SRCHSER | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/SRCHSER.cobol | `ACCT-REC` → DD `ACCTREC` (R) | — |
| CBL0106 | COBOL Programming Course #3 - Advanced Topics/Challenges/Debugging/cbl/CBL0106.cbl | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | `copybooks/ACCT-FIELDS.cpy` (derived), `copybooks/PRINT-REC-B.cpy` (derived) |
| CBL0106C | COBOL Programming Course #3 - Advanced Topics/Challenges/Debugging/cbl/CBL0106C.cbl | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | `copybooks/ACCT-FIELDS.cpy` (derived), `copybooks/PRINT-REC-B.cpy` (derived) |
| CBLDB21 | COBOL Programming Course #3 - Advanced Topics/Labs/cbl/CBLDB21.cbl | `REPOUT` → DD `UT-S-REPORT` (W)<br>DB2 `Z#####T` (R) | `SQLCA` (EXEC SQL INCLUDE), `copybooks/REPREC.cpy` (derived) |
| CBLDB22 | COBOL Programming Course #3 - Advanced Topics/Labs/cbl/CBLDB22.cbl | `REPOUT` → DD `UT-S-REPORT` (W)<br>`RECIN` → DD `DA-S-RECIN` (R)<br>DB2 `Z#####T` (R) | `SQLCA` (EXEC SQL INCLUDE), `copybooks/REPREC.cpy` (derived) |
| CBLDB23 | COBOL Programming Course #3 - Advanced Topics/Labs/cbl/CBLDB23.cbl | `REPOUT` → DD `UT-S-REPORT` (W)<br>`CARDIN` → DD `DA-S-CARDIN` (R)<br>DB2 `Z#####T` (R) | `SQLCA` (EXEC SQL INCLUDE) |
| DEPTPAY | COBOL Programming Course #4 - Testing/Labs/cbl/DEPTPAY.CBL | — | — |
| EMPPAY | COBOL Programming Course #4 - Testing/Labs/cbl/EMPPAY.CBL | — | — |
