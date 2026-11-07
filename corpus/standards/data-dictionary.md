# Keystone Federal Bank: Legacy Data Dictionary

| | |
|---|---|
| Document ID | KFB-STD-003 |
| Scope | Every record field defined in an `FD` entry or copybook in `corpus/legacy` (including the derived copybooks in `corpus/legacy/copybooks/`) |
| Related | `pic-mapping.md` (types, byte lengths), `coding-standards.md` §3–§4 (parsing, PII logging) |

Keystone Federal Bank is a fictional institution. Every field name below appears in `corpus/legacy` exactly as written. Citations are `file:line` relative to `corpus/legacy/`, using these abbreviations:

- `C2/` = `COBOL Programming Course #2 - Learning COBOL/Labs/cbl/`
- `C3/` = `COBOL Programming Course #3 - Advanced Topics/Labs/cbl/`
- `C3D/` = `COBOL Programming Course #3 - Advanced Topics/Challenges/Debugging/cbl/`

## Scope notes

- **Copybooks:** the original course has no copybooks, and no program uses a `COPY` statement. Every field here comes from an `FD` in the program source. ModernizeOps has extracted each FD record layout repeated verbatim across two or more programs into a **derived copybook** in `corpus/legacy/copybooks/` (header: *DERIVED COPYBOOK - extracted by ModernizeOps from inline FD in …; originals unchanged*). The programs do not `COPY` them and were not modified. Derived copybooks are cited below as `copybooks/<NAME>.cpy:<lines>`, giving the lines of the record definition after the header. The only `EXEC SQL INCLUDE` is `SQLCA` (e.g. `C3/CBLDB21.cbl:38`), DB2's built-in communication area, which is not a record layout.

  | Derived copybook | Record | Bytes | Section |
  |---|---|---|---|
  | `copybooks/ACCT-FIELDS.cpy:12-23` | `ACCT-FIELDS` | 170 | §1 |
  | `copybooks/PRINT-REC-A.cpy:10-16` | `PRINT-REC` (Layout A) | 119 | §2.1 |
  | `copybooks/PRINT-REC-B.cpy:13-21` | `PRINT-REC` (Layout B) | 62 | §2.2 |
  | `copybooks/REPREC.cpy:9-15` | `REPREC` (`CBLDB21`/`CBLDB22`) | 119 | §5.1 |
- **Not included:** WORKING-STORAGE items, and the DB2 table declaration `Z#####T` (`C3/CBLDB21.cbl:53-63`), which is not an FD. Its columns map one-to-one onto `ACCT-FIELDS` (`ACCTNO`↔`ACCT-NO`, `LIMIT`↔`ACCT-LIMIT`, `SURNAME`↔`LAST-NAME`, and so on).
- **Main tables:** each table cites one representative definition per field. **Appendix A** lists every occurrence of every field.
- **Offsets:** 1-based byte positions within the record. Byte lengths follow `pic-mapping.md`.
- **Meaning:** taken from the field name and how the program uses it (cited where a `MOVE` makes it clear). This is course sample data, so the business meanings are descriptive, not authoritative.

### PII flag

| Flag | Meaning | Handling (see coding-standards §4) |
|---|---|---|
| **Yes** | Identifies a customer or account, or is nonpublic personal financial information | Mask or omit in logs; synthetic data only in tests |
| **Possible** | Free text that may contain personal data | Omit from logs |
| **No** | No personal data | No restriction |

Balances and limits are flagged **Yes** because, together with an account number or name, they are nonpublic personal financial information.

---

## 1. `ACCT-REC` → record `ACCT-FIELDS` (account master input, 170 bytes)

DD `ACCTREC`, read (`OPEN INPUT`) by 18 programs (see `INVENTORY.md`). Sixteen of them define the structure below, and two declare the record undivided (§1.1).

Canonical definition: `C2/CBL0001.cobol:41-55`. The same layout appears in `C2/CBL0002`, `CBL0004`–`CBL0006`, `CBL0008`, `CBL0009`, `CBL0011`, `CBL0012`, `CBL0033`, `CBL006A`, `CBLC1`, `C3D/CBL0106` and `C3D/CBL0106C`. Variants are listed in §1.1.

Derived copybook: `copybooks/ACCT-FIELDS.cpy:12-23`, extracted from the 14 identical definitions. The variants in §1.1 (`CBL0007`, `CBL0010`, `SRCHBIN`, `SRCHSER`) are not covered by it.

| Level | Field | PIC / USAGE | Offset | Bytes | Meaning | PII | Cite |
|---|---|---|---|---|---|---|---|
| 01 | `ACCT-FIELDS` | group | 1 | 170 | Whole account record | Yes | `C2/CBL0001.cobol:42` |
| 05 | `ACCT-NO` | `X(8)` | 1 | 8 | Account number (record key; table search key in `C2/SRCHBIN.cobol:30`) | Yes | `C2/CBL0001.cobol:43` |
| 05 | `ACCT-LIMIT` | `S9(7)V99 COMP-3` | 9 | 5 | Account limit, signed, 2 decimals; totaled into `TLIMIT` (`C2/CBL0010.cobol:173`) | Yes | `C2/CBL0001.cobol:44` |
| 05 | `ACCT-BALANCE` | `S9(7)V99 COMP-3` | 14 | 5 | Current account balance, signed, 2 decimals | Yes | `C2/CBL0001.cobol:45` |
| 05 | `LAST-NAME` | `X(20)` | 19 | 20 | Customer surname (DB2 equivalent `SURNAME`, `C3/CBLDB21.cbl:57`) | Yes | `C2/CBL0001.cobol:48` |
| 05 | `FIRST-NAME` | `X(15)` | 39 | 15 | Customer first name | Yes | `C2/CBL0001.cobol:49` |
| 05 | `CLIENT-ADDR` | group | 54 | 60 | Customer postal address | Yes | `C2/CBL0001.cobol:50` |
| 10 | `STREET-ADDR` | `X(25)` | 54 | 25 | Street address line | Yes | `C2/CBL0001.cobol:51` |
| 10 | `CITY-COUNTY` | `X(20)` | 79 | 20 | City or county | Yes | `C2/CBL0001.cobol:52` |
| 10 | `USA-STATE` | `X(15)` | 99 | 15 | U.S. state name, spelled out (e.g. `'Virginia'`, `C2/CBL0007.cobol:42`) | Yes | `C2/CBL0001.cobol:53` |
| 05 | `RESERVED` | `X(7)` | 114 | 7 | Unused; preserve the bytes as-is | No | `C2/CBL0001.cobol:54` |
| 05 | `COMMENTS` | `X(50)` | 121 | 50 | Free-text account comment | Possible | `C2/CBL0001.cobol:55` |

### 1.1 Variants of `ACCT-FIELDS`

| Program | Difference | Effect | Cite |
|---|---|---|---|
| `CBL0007` | Adds condition name `88 STATE VALUE 'Virginia'` under `USA-STATE` | No storage; true when `USA-STATE` = `'Virginia'` | `C2/CBL0007.cobol:42` |
| `CBL0010` | `ACCT-LIMIT PIC S9(7)V99` with **no `COMP-3`** (zoned, 9 bytes) | Record becomes 174 bytes. Every field after `ACCT-LIMIT` shifts by 4 bytes, so a 170-byte `ACCTREC` file is misread. Treat this as a legacy defect (see coding-standards §1). | `C2/CBL0010.cobol:34` |
| `SRCHBIN`, `SRCHSER` | Record declared as one `PIC X(170)` item; the structure is applied in WORKING-STORAGE (`ACCT-TABLE-ITEM`) | Same 170 bytes, undivided at FD level | `C2/SRCHBIN.cobol:20`, `C2/SRCHSER.cobol:20` |

---

## 2. `PRINT-LINE` → record `PRINT-REC` (account report output)

DD `PRTLINE`, written (`OPEN OUTPUT`). There are three layouts.

### 2.1 Layout A: full detail line (119 bytes)

`C2/CBL0001.cobol:28-37`. Also in `C2/CBL0002` and `C2/CBL0033`. Derived copybook: `copybooks/PRINT-REC-A.cpy:10-16`.

| Level | Field | PIC | Offset | Bytes | Meaning | PII | Cite |
|---|---|---|---|---|---|---|---|
| 01 | `PRINT-REC` | group | 1 | 119 | Report detail line | Yes | `C2/CBL0001.cobol:28` |
| 05 | `ACCT-NO-O` | `X(8)` | 1 | 8 | Account number (from `ACCT-NO`) | Yes | `C2/CBL0001.cobol:29` |
| 05 | `ACCT-LIMIT-O` | `$$,$$$,$$9.99` | 9 | 13 | Edited account limit (from `ACCT-LIMIT`, `C2/CBL0001.cobol:92`) | Yes | `C2/CBL0001.cobol:30` |
| 05 | `ACCT-BALANCE-O` | `$$,$$$,$$9.99` | 22 | 13 | Edited account balance | Yes | `C2/CBL0001.cobol:31` |
| 05 | `LAST-NAME-O` | `X(20)` | 35 | 20 | Customer surname | Yes | `C2/CBL0001.cobol:35` |
| 05 | `FIRST-NAME-O` | `X(15)` | 55 | 15 | Customer first name | Yes | `C2/CBL0001.cobol:36` |
| 05 | `COMMENTS-O` | `X(50)` | 70 | 50 | Account comment (from `COMMENTS`, `C2/CBL0001.cobol:96`) | Possible | `C2/CBL0001.cobol:37` |

### 2.2 Layout B: columnar line with spacers (62 bytes)

`C2/CBL0004.cobol:24-42`. Also in `C2/CBL0006`–`CBL0012`, `CBL006A`, `CBLC1`, `C3D/CBL0106` and `C3D/CBL0106C`. Derived copybook: `copybooks/PRINT-REC-B.cpy:13-21`. Layout C (§2.3) is not covered by it.

| Level | Field | PIC | Offset | Bytes | Meaning | PII | Cite |
|---|---|---|---|---|---|---|---|
| 01 | `PRINT-REC` | group | 1 | 62 | Report detail line | Yes | `C2/CBL0004.cobol:24` |
| 05 | `ACCT-NO-O` | `X(8)` | 1 | 8 | Account number | Yes | `C2/CBL0004.cobol:25` |
| 05 | `FILLER` | `X(02)` | 9 | 2 | Column spacer | No | `C2/CBL0004.cobol:26` |
| 05 | `LAST-NAME-O` | `X(20)` | 11 | 20 | Customer surname | Yes | `C2/CBL0004.cobol:30` |
| 05 | `FILLER` | `X(02)` | 31 | 2 | Column spacer | No | `C2/CBL0004.cobol:31` |
| 05 | `ACCT-LIMIT-O` | `$$,$$$,$$9.99` | 33 | 13 | Edited account limit | Yes | `C2/CBL0004.cobol:36` |
| 05 | `FILLER` | `X(02)` | 46 | 2 | Column spacer | No | `C2/CBL0004.cobol:40` |
| 05 | `ACCT-BALANCE-O` | `$$,$$$,$$9.99` | 48 | 13 | Edited account balance | Yes | `C2/CBL0004.cobol:41` |
| 05 | `FILLER` | `X(02)` | 61 | 2 | Trailing spacer | No | `C2/CBL0004.cobol:42` |

### 2.3 Layout C: as Layout B, with zero-suppressed amounts (62 bytes)

`C2/CBL0005.cobol:24-42`. Identical to Layout B except for these two fields:

| Level | Field | PIC | Offset | Bytes | Meaning | PII | Cite |
|---|---|---|---|---|---|---|---|
| 05 | `ACCT-LIMIT-O` | `ZZ,ZZZ,ZZ9.99` | 33 | 13 | Edited account limit, no currency sign | Yes | `C2/CBL0005.cobol:36` |
| 05 | `ACCT-BALANCE-O` | `ZZ,ZZZ,ZZ9.99` | 48 | 13 | Edited account balance, no currency sign | Yes | `C2/CBL0005.cobol:41` |

---

## 3. `PRT-LINE` → record `PRT-REC` (counter output, 5 bytes)

DD `PRTLINE`, program `COBOL`. The FD declares `RECORD CONTAINS 5 CHARACTERS RECORDING MODE F` (`C2/COBOL.cobol:18`).

| Level | Field | PIC | Offset | Bytes | Meaning | PII | Cite |
|---|---|---|---|---|---|---|---|
| 01 | `PRT-REC` | `9(05)` | 1 | 5 | Program counter value (written from `PGM-COUNT`, `C2/COBOL.cobol:57`) | No | `C2/COBOL.cobol:19` |

## 4. `PRT-DONE` → record `PRT-REC-DONE` (completion line, 80 bytes)

DD `PRTDONE`, program `COBOL`. The FD declares `RECORD CONTAINS 80 CHARACTERS` (`C2/COBOL.cobol:21`).

| Level | Field | PIC | Offset | Bytes | Meaning | PII | Cite |
|---|---|---|---|---|---|---|---|
| 01 | `PRT-REC-DONE` | group | 1 | 80 | Run-completion line | Yes | `C2/COBOL.cobol:22` |
| 05 | `PRT-DATE` | `X(8)` | 1 | 8 | Run date, `YYYYMMDD` (`C2/COBOL.cobol:63`) | No | `C2/COBOL.cobol:23` |
| 05 | `FILLER` | `X(1)` | 9 | 1 | Spacer | No | `C2/COBOL.cobol:24` |
| 05 | `PRT-TIME` | `X(4)` | 10 | 4 | Run time, `HHMM` (first 4 characters of the time, `C2/COBOL.cobol:64`) | No | `C2/COBOL.cobol:25` |
| 05 | `FILLER` | `X(2)` | 14 | 2 | Spacer | No | `C2/COBOL.cobol:26` |
| 05 | `PRT-COMMENT` | `X(27)` | 16 | 27 | Fixed message text (`C2/COBOL.cobol:65`) | No | `C2/COBOL.cobol:27` |
| 05 | `FILLER` | `X(2)` | 43 | 2 | Spacer | No | `C2/COBOL.cobol:28` |
| 05 | `MY-NAME` | `X(36)` | 45 | 36 | Name of the person running the program (not populated anywhere in the source) | Yes | `C2/COBOL.cobol:29` |

---

## 5. `REPOUT` → record `REPREC` (DB2 account report output)

DD `UT-S-REPORT`, written by the DB2 programs. Fields are filled from the host variables fetched from table `Z#####T`.

### 5.1 `CBLDB21` / `CBLDB22` layout (119 bytes)

`C3/CBLDB21.cbl:26-32`. Same layout in `C3/CBLDB22.cbl:27-33`. Derived copybook: `copybooks/REPREC.cpy:9-15`. The `CBLDB23` `REPREC` (§5.2) differs and is not covered by it.

| Level | Field | PIC | Offset | Bytes | Meaning | PII | Cite |
|---|---|---|---|---|---|---|---|
| 01 | `REPREC` | group | 1 | 119 | Report detail line | Yes | `C3/CBLDB21.cbl:26` |
| 05 | `ACCT-NO-O` | `X(8)` | 1 | 8 | Account number (column `ACCTNO`) | Yes | `C3/CBLDB21.cbl:27` |
| 05 | `ACCT-LIMIT-O` | `$$,$$$,$$9.99` | 9 | 13 | Edited account limit (column `LIMIT DECIMAL(9,2)`) | Yes | `C3/CBLDB21.cbl:28` |
| 05 | `ACCT-BALANCE-O` | `$$,$$$,$$9.99` | 22 | 13 | Edited account balance (column `BALANCE DECIMAL(9,2)`) | Yes | `C3/CBLDB21.cbl:29` |
| 05 | `ACCT-LASTN-O` | `X(20)` | 35 | 20 | Customer surname (from `ACCT-LASTN`, `C3/CBLDB21.cbl:127`) | Yes | `C3/CBLDB21.cbl:30` |
| 05 | `ACCT-FIRSTN-O` | `X(15)` | 55 | 15 | Customer first name | Yes | `C3/CBLDB21.cbl:31` |
| 05 | `ACCT-COMMENT-O` | `X(50)` | 70 | 50 | Account comment (from `ACCT-COMMENT`, `C3/CBLDB21.cbl:129`) | Possible | `C3/CBLDB21.cbl:32` |

### 5.2 `CBLDB23` layout (58 bytes)

`C3/CBLDB23.cbl:28-32`.

| Level | Field | PIC | Offset | Bytes | Meaning | PII | Cite |
|---|---|---|---|---|---|---|---|
| 01 | `REPREC` | group | 1 | 58 | Report detail line | Yes | `C3/CBLDB23.cbl:28` |
| 05 | `ACCT-NO-O` | `X(8)` | 1 | 8 | Account number | Yes | `C3/CBLDB23.cbl:29` |
| 05 | `ACCT-LASTN-O` | `X(20)` | 9 | 20 | Customer surname (`C3/CBLDB23.cbl:171`) | Yes | `C3/CBLDB23.cbl:30` |
| 05 | `ACCT-FIRSTN-O` | `X(15)` | 29 | 15 | Customer first name | Yes | `C3/CBLDB23.cbl:31` |
| 05 | `ACCT-ADDR3-O` | `X(15)` | 44 | 15 | Third address line, i.e. state (from `ACCT-ADDR3`, `C3/CBLDB23.cbl:173`; column `ADDRESS3 CHAR(15)` matches `USA-STATE X(15)`) | Yes | `C3/CBLDB23.cbl:32` |

---

## 6. Card/record input files (80 bytes, undivided)

| FD | DD | Level | Field | PIC | Bytes | Meaning | PII | Cite |
|---|---|---|---|---|---|---|---|---|
| `RECIN` | `DA-S-RECIN` | 01 | `INREC` | `X(80)` | 80 | Input card image, read `INTO IOAREA` (structure defined in WORKING-STORAGE) | Possible | `C3/CBLDB22.cbl:41` |
| `CARDIN` | `DA-S-CARDIN` | 01 | `CARDREC` | `X(80)` | 80 | Input card image, read `INTO IOAREA` | Possible | `C3/CBLDB23.cbl:38` |

---

## Appendix A: Every FD field occurrence

Generated from the program source; `FILLER` entries are omitted. 33 field names, 308 definitions. Derived copybooks are not counted here; they repeat definitions listed above.

| Field | Occurrences (file:line) |
|---|---|
| `ACCT-ADDR3-O` | `C3/CBLDB23.cbl:32` |
| `ACCT-BALANCE` | `C2/CBL0001.cobol:45`, `C2/CBL0002.cobol:33`, `C2/CBL0004.cobol:47`, `C2/CBL0005.cobol:47`, `C2/CBL0006.cobol:35`, `C2/CBL0007.cobol:35`, `C2/CBL0008.cobol:35`, `C2/CBL0009.cobol:35`, `C2/CBL0010.cobol:35`, `C2/CBL0011.cobol:35`, `C2/CBL0012.cobol:35`, `C2/CBL0033.cobol:33`, `C2/CBL006A.cobol:32`, `C2/CBLC1.cobol:32`, `C3D/CBL0106.cbl:35`, `C3D/CBL0106C.cbl:35` |
| `ACCT-BALANCE-O` | `C2/CBL0001.cobol:31`, `C2/CBL0002.cobol:24`, `C2/CBL0004.cobol:41`, `C2/CBL0005.cobol:41`, `C2/CBL0006.cobol:28`, `C2/CBL0007.cobol:28`, `C2/CBL0008.cobol:28`, `C2/CBL0009.cobol:28`, `C2/CBL0010.cobol:28`, `C2/CBL0011.cobol:28`, `C2/CBL0012.cobol:28`, `C2/CBL0033.cobol:24`, `C2/CBL006A.cobol:25`, `C2/CBLC1.cobol:25`, `C3D/CBL0106.cbl:28`, `C3D/CBL0106C.cbl:28`, `C3/CBLDB21.cbl:29`, `C3/CBLDB22.cbl:30` |
| `ACCT-COMMENT-O` | `C3/CBLDB21.cbl:32`, `C3/CBLDB22.cbl:33` |
| `ACCT-FIELDS` | `C2/CBL0001.cobol:42`, `C2/CBL0002.cobol:30`, `C2/CBL0004.cobol:44`, `C2/CBL0005.cobol:44`, `C2/CBL0006.cobol:32`, `C2/CBL0007.cobol:32`, `C2/CBL0008.cobol:32`, `C2/CBL0009.cobol:32`, `C2/CBL0010.cobol:32`, `C2/CBL0011.cobol:32`, `C2/CBL0012.cobol:32`, `C2/CBL0033.cobol:30`, `C2/CBL006A.cobol:29`, `C2/CBLC1.cobol:29`, `C2/SRCHBIN.cobol:20`, `C2/SRCHSER.cobol:20`, `C3D/CBL0106.cbl:32`, `C3D/CBL0106C.cbl:32` |
| `ACCT-FIRSTN-O` | `C3/CBLDB21.cbl:31`, `C3/CBLDB22.cbl:32`, `C3/CBLDB23.cbl:31` |
| `ACCT-LASTN-O` | `C3/CBLDB21.cbl:30`, `C3/CBLDB22.cbl:31`, `C3/CBLDB23.cbl:30` |
| `ACCT-LIMIT` | `C2/CBL0001.cobol:44`, `C2/CBL0002.cobol:32`, `C2/CBL0004.cobol:46`, `C2/CBL0005.cobol:46`, `C2/CBL0006.cobol:34`, `C2/CBL0007.cobol:34`, `C2/CBL0008.cobol:34`, `C2/CBL0009.cobol:34`, `C2/CBL0010.cobol:34`, `C2/CBL0011.cobol:34`, `C2/CBL0012.cobol:34`, `C2/CBL0033.cobol:32`, `C2/CBL006A.cobol:31`, `C2/CBLC1.cobol:31`, `C3D/CBL0106.cbl:34`, `C3D/CBL0106C.cbl:34` |
| `ACCT-LIMIT-O` | `C2/CBL0001.cobol:30`, `C2/CBL0002.cobol:23`, `C2/CBL0004.cobol:36`, `C2/CBL0005.cobol:36`, `C2/CBL0006.cobol:26`, `C2/CBL0007.cobol:26`, `C2/CBL0008.cobol:26`, `C2/CBL0009.cobol:26`, `C2/CBL0010.cobol:26`, `C2/CBL0011.cobol:26`, `C2/CBL0012.cobol:26`, `C2/CBL0033.cobol:23`, `C2/CBL006A.cobol:23`, `C2/CBLC1.cobol:23`, `C3D/CBL0106.cbl:26`, `C3D/CBL0106C.cbl:26`, `C3/CBLDB21.cbl:28`, `C3/CBLDB22.cbl:29` |
| `ACCT-NO` | `C2/CBL0001.cobol:43`, `C2/CBL0002.cobol:31`, `C2/CBL0004.cobol:45`, `C2/CBL0005.cobol:45`, `C2/CBL0006.cobol:33`, `C2/CBL0007.cobol:33`, `C2/CBL0008.cobol:33`, `C2/CBL0009.cobol:33`, `C2/CBL0010.cobol:33`, `C2/CBL0011.cobol:33`, `C2/CBL0012.cobol:33`, `C2/CBL0033.cobol:31`, `C2/CBL006A.cobol:30`, `C2/CBLC1.cobol:30`, `C3D/CBL0106.cbl:33`, `C3D/CBL0106C.cbl:33` |
| `ACCT-NO-O` | `C2/CBL0001.cobol:29`, `C2/CBL0002.cobol:22`, `C2/CBL0004.cobol:25`, `C2/CBL0005.cobol:25`, `C2/CBL0006.cobol:22`, `C2/CBL0007.cobol:22`, `C2/CBL0008.cobol:22`, `C2/CBL0009.cobol:22`, `C2/CBL0010.cobol:22`, `C2/CBL0011.cobol:22`, `C2/CBL0012.cobol:22`, `C2/CBL0033.cobol:22`, `C2/CBL006A.cobol:19`, `C2/CBLC1.cobol:19`, `C3D/CBL0106.cbl:22`, `C3D/CBL0106C.cbl:22`, `C3/CBLDB21.cbl:27`, `C3/CBLDB22.cbl:28`, `C3/CBLDB23.cbl:29` |
| `CARDREC` | `C3/CBLDB23.cbl:38` |
| `CITY-COUNTY` | `C2/CBL0001.cobol:52`, `C2/CBL0002.cobol:38`, `C2/CBL0004.cobol:52`, `C2/CBL0005.cobol:52`, `C2/CBL0006.cobol:40`, `C2/CBL0007.cobol:40`, `C2/CBL0008.cobol:40`, `C2/CBL0009.cobol:40`, `C2/CBL0010.cobol:40`, `C2/CBL0011.cobol:40`, `C2/CBL0012.cobol:40`, `C2/CBL0033.cobol:38`, `C2/CBL006A.cobol:37`, `C2/CBLC1.cobol:37`, `C3D/CBL0106.cbl:40`, `C3D/CBL0106C.cbl:40` |
| `CLIENT-ADDR` | `C2/CBL0001.cobol:50`, `C2/CBL0002.cobol:36`, `C2/CBL0004.cobol:50`, `C2/CBL0005.cobol:50`, `C2/CBL0006.cobol:38`, `C2/CBL0007.cobol:38`, `C2/CBL0008.cobol:38`, `C2/CBL0009.cobol:38`, `C2/CBL0010.cobol:38`, `C2/CBL0011.cobol:38`, `C2/CBL0012.cobol:38`, `C2/CBL0033.cobol:36`, `C2/CBL006A.cobol:35`, `C2/CBLC1.cobol:35`, `C3D/CBL0106.cbl:38`, `C3D/CBL0106C.cbl:38` |
| `COMMENTS` | `C2/CBL0001.cobol:55`, `C2/CBL0002.cobol:41`, `C2/CBL0004.cobol:55`, `C2/CBL0005.cobol:55`, `C2/CBL0006.cobol:43`, `C2/CBL0007.cobol:49`, `C2/CBL0008.cobol:43`, `C2/CBL0009.cobol:43`, `C2/CBL0010.cobol:43`, `C2/CBL0011.cobol:43`, `C2/CBL0012.cobol:43`, `C2/CBL0033.cobol:41`, `C2/CBL006A.cobol:40`, `C2/CBLC1.cobol:40`, `C3D/CBL0106.cbl:43`, `C3D/CBL0106C.cbl:43` |
| `COMMENTS-O` | `C2/CBL0001.cobol:37`, `C2/CBL0002.cobol:27`, `C2/CBL0033.cobol:27` |
| `FIRST-NAME` | `C2/CBL0001.cobol:49`, `C2/CBL0002.cobol:35`, `C2/CBL0004.cobol:49`, `C2/CBL0005.cobol:49`, `C2/CBL0006.cobol:37`, `C2/CBL0007.cobol:37`, `C2/CBL0008.cobol:37`, `C2/CBL0009.cobol:37`, `C2/CBL0010.cobol:37`, `C2/CBL0011.cobol:37`, `C2/CBL0012.cobol:37`, `C2/CBL0033.cobol:35`, `C2/CBL006A.cobol:34`, `C2/CBLC1.cobol:34`, `C3D/CBL0106.cbl:37`, `C3D/CBL0106C.cbl:37` |
| `FIRST-NAME-O` | `C2/CBL0001.cobol:36`, `C2/CBL0002.cobol:26`, `C2/CBL0033.cobol:26` |
| `INREC` | `C3/CBLDB22.cbl:41` |
| `LAST-NAME` | `C2/CBL0001.cobol:48`, `C2/CBL0002.cobol:34`, `C2/CBL0004.cobol:48`, `C2/CBL0005.cobol:48`, `C2/CBL0006.cobol:36`, `C2/CBL0007.cobol:36`, `C2/CBL0008.cobol:36`, `C2/CBL0009.cobol:36`, `C2/CBL0010.cobol:36`, `C2/CBL0011.cobol:36`, `C2/CBL0012.cobol:36`, `C2/CBL0033.cobol:34`, `C2/CBL006A.cobol:33`, `C2/CBLC1.cobol:33`, `C3D/CBL0106.cbl:36`, `C3D/CBL0106C.cbl:36` |
| `LAST-NAME-O` | `C2/CBL0001.cobol:35`, `C2/CBL0002.cobol:25`, `C2/CBL0004.cobol:30`, `C2/CBL0005.cobol:30`, `C2/CBL0006.cobol:24`, `C2/CBL0007.cobol:24`, `C2/CBL0008.cobol:24`, `C2/CBL0009.cobol:24`, `C2/CBL0010.cobol:24`, `C2/CBL0011.cobol:24`, `C2/CBL0012.cobol:24`, `C2/CBL0033.cobol:25`, `C2/CBL006A.cobol:21`, `C2/CBLC1.cobol:21`, `C3D/CBL0106.cbl:24`, `C3D/CBL0106C.cbl:24` |
| `MY-NAME` | `C2/COBOL.cobol:29` |
| `PRINT-REC` | `C2/CBL0001.cobol:28`, `C2/CBL0002.cobol:21`, `C2/CBL0004.cobol:24`, `C2/CBL0005.cobol:24`, `C2/CBL0006.cobol:21`, `C2/CBL0007.cobol:21`, `C2/CBL0008.cobol:21`, `C2/CBL0009.cobol:21`, `C2/CBL0010.cobol:21`, `C2/CBL0011.cobol:21`, `C2/CBL0012.cobol:21`, `C2/CBL0033.cobol:21`, `C2/CBL006A.cobol:18`, `C2/CBLC1.cobol:18`, `C3D/CBL0106.cbl:21`, `C3D/CBL0106C.cbl:21` |
| `PRT-COMMENT` | `C2/COBOL.cobol:27` |
| `PRT-DATE` | `C2/COBOL.cobol:23` |
| `PRT-REC` | `C2/COBOL.cobol:19` |
| `PRT-REC-DONE` | `C2/COBOL.cobol:22` |
| `PRT-TIME` | `C2/COBOL.cobol:25` |
| `REPREC` | `C3/CBLDB21.cbl:26`, `C3/CBLDB22.cbl:27`, `C3/CBLDB23.cbl:28` |
| `RESERVED` | `C2/CBL0001.cobol:54`, `C2/CBL0002.cobol:40`, `C2/CBL0004.cobol:54`, `C2/CBL0005.cobol:54`, `C2/CBL0006.cobol:42`, `C2/CBL0007.cobol:48`, `C2/CBL0008.cobol:42`, `C2/CBL0009.cobol:42`, `C2/CBL0010.cobol:42`, `C2/CBL0011.cobol:42`, `C2/CBL0012.cobol:42`, `C2/CBL0033.cobol:40`, `C2/CBL006A.cobol:39`, `C2/CBLC1.cobol:39`, `C3D/CBL0106.cbl:42`, `C3D/CBL0106C.cbl:42` |
| `STATE` | `C2/CBL0007.cobol:42` |
| `STREET-ADDR` | `C2/CBL0001.cobol:51`, `C2/CBL0002.cobol:37`, `C2/CBL0004.cobol:51`, `C2/CBL0005.cobol:51`, `C2/CBL0006.cobol:39`, `C2/CBL0007.cobol:39`, `C2/CBL0008.cobol:39`, `C2/CBL0009.cobol:39`, `C2/CBL0010.cobol:39`, `C2/CBL0011.cobol:39`, `C2/CBL0012.cobol:39`, `C2/CBL0033.cobol:37`, `C2/CBL006A.cobol:36`, `C2/CBLC1.cobol:36`, `C3D/CBL0106.cbl:39`, `C3D/CBL0106C.cbl:39` |
| `USA-STATE` | `C2/CBL0001.cobol:53`, `C2/CBL0002.cobol:39`, `C2/CBL0004.cobol:53`, `C2/CBL0005.cobol:53`, `C2/CBL0006.cobol:41`, `C2/CBL0007.cobol:41`, `C2/CBL0008.cobol:41`, `C2/CBL0009.cobol:41`, `C2/CBL0010.cobol:41`, `C2/CBL0011.cobol:41`, `C2/CBL0012.cobol:41`, `C2/CBL0033.cobol:39`, `C2/CBL006A.cobol:38`, `C2/CBLC1.cobol:38`, `C3D/CBL0106.cbl:41`, `C3D/CBL0106C.cbl:41` |
