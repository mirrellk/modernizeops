# MOD-1: Port the account report to Python and flag accounts over limit

## Description

Port CBL0008 to a Python module that reads the sample account file (ACCTREC, corpus/legacy/COBOL Programming Course #2 - Learning COBOL/Labs/data/data) and produces the same report as CBL0008.cobol, except for the changes below.

Changes:

1. Detail line: add a 1-byte OVER-LIMIT flag preceded by 2 spaces (bytes 63-64 spaces, byte 65 flag). Value Y when ACCT-BALANCE > ACCT-LIMIT, else N (equal = N). No printed heading; header text unchanged.
2. Record length: ALL print lines (header, detail and totals) become 65 bytes, fixed length; header and totals lines are padded with spaces on the right.
3. Byte positions refer to the logical print record, excluding any ASA carriage-control byte. The Python output writes no carriage-control byte.

Testing: expected totals and test records may be derived from the sample file. One synthetic record with ACCT-BALANCE = ACCT-LIMIT is approved for tests only (the sample file has no such record).

Acceptance: TLIMIT and TBALANCE (sums of ACCT-LIMIT and ACCT-BALANCE over all records, printed by WRITE-TLIMIT-TBALANCE) equal the COBOL values for the sample file; OVER-LIMIT correct for one record below, one equal to (synthetic) and one above the limit; every output line is 65 bytes; apart from the new bytes, padding and run date, output matches CBL0008 byte for byte. The run date is masked for test comparison only.

This description supersedes earlier comments.

## Comments

None.
