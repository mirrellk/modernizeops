# Legacy Program Inventory

Source: the Open Mainframe Project COBOL Programming Course (see `LICENSE`).
This file has one row per COBOL program, built from the code itself (comment lines in column 7 are ignored):

- **PROGRAM-ID**: from the `IDENTIFICATION DIVISION`.
- **Files read/written**: each `SELECT … ASSIGN TO` gives the internal file name and its DD name. The mode comes from the `OPEN` statements: R = `INPUT`, W = `OUTPUT`, RW = `I-O`. DB2 tables come from `EXEC SQL` cursors and statements. Plain `ACCEPT` reads from SYSIN.
- **Copybooks**: `COPY` statements and `EXEC SQL INCLUDE` members.

Notes:
- The corpus has no `.cpy` copybooks, and no program uses a `COPY` statement. The only include is `SQLCA`, which is DB2's built-in SQL communication area, not a copybook from this corpus.
- `CBLC1.cobol` declares `PROGRAM-ID. CBL0006`, the same name as `CBL0006.cobol`.
- `Z#####T` is the course's placeholder DB2 table name (learners replace `#####` with their user ID).
- `DISPLAY` output to SYSOUT is not listed.

| PROGRAM-ID | Source | Files read/written | Copybooks |
|---|---|---|---|
| ADDAMT | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/ADDAMT.cobol | SYSIN via `ACCEPT` (R) | — |
| CBL0001 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0001.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | — |
| CBL0002 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0002.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | — |
| CBL0004 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0004.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | — |
| CBL0005 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0005.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | — |
| CBL0006 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0006.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | — |
| CBL0007 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0007.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | — |
| CBL0008 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0008.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | — |
| CBL0009 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0009.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | — |
| CBL0010 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0010.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | — |
| CBL0011 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0011.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | — |
| CBL0012 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0012.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | — |
| CBL0013 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0013.cobol | — | — |
| CBL0014 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0014.cobol | — | — |
| CBL0015 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0015.cobol | — | — |
| CBL0033 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0033.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | — |
| CBL006A | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL006A.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | — |
| CBL0006 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBLC1.cobol | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | — |
| CBLC2 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBLC2.cobol | — | — |
| COBOL | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/COBOL.cobol | `PRT-LINE` → DD `PRTLINE` (W)<br>`PRT-DONE` → DD `PRTDONE` (W) | — |
| HELLO | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/HELLO.cobol | — | — |
| PAYROL00 | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/PAYROL00.cobol | — | — |
| PAYROL0X | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/PAYROL0X.cobol | — | — |
| SRCHBIN | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/SRCHBIN.cobol | `ACCT-REC` → DD `ACCTREC` (R) | — |
| SRCHSER | COBOL Programming Course #2 - Learning COBOL/Labs/cbl/SRCHSER.cobol | `ACCT-REC` → DD `ACCTREC` (R) | — |
| CBL0106 | COBOL Programming Course #3 - Advanced Topics/Challenges/Debugging/cbl/CBL0106.cbl | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | — |
| CBL0106C | COBOL Programming Course #3 - Advanced Topics/Challenges/Debugging/cbl/CBL0106C.cbl | `PRINT-LINE` → DD `PRTLINE` (W)<br>`ACCT-REC` → DD `ACCTREC` (R) | — |
| CBLDB21 | COBOL Programming Course #3 - Advanced Topics/Labs/cbl/CBLDB21.cbl | `REPOUT` → DD `UT-S-REPORT` (W)<br>DB2 `Z#####T` (R) | `SQLCA` (EXEC SQL INCLUDE) |
| CBLDB22 | COBOL Programming Course #3 - Advanced Topics/Labs/cbl/CBLDB22.cbl | `REPOUT` → DD `UT-S-REPORT` (W)<br>`RECIN` → DD `DA-S-RECIN` (R)<br>DB2 `Z#####T` (R) | `SQLCA` (EXEC SQL INCLUDE) |
| CBLDB23 | COBOL Programming Course #3 - Advanced Topics/Labs/cbl/CBLDB23.cbl | `REPOUT` → DD `UT-S-REPORT` (W)<br>`CARDIN` → DD `DA-S-CARDIN` (R)<br>DB2 `Z#####T` (R) | `SQLCA` (EXEC SQL INCLUDE) |
| DEPTPAY | COBOL Programming Course #4 - Testing/Labs/cbl/DEPTPAY.CBL | — | — |
| EMPPAY | COBOL Programming Course #4 - Testing/Labs/cbl/EMPPAY.CBL | — | — |
