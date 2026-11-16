# MOD-902: Hide first names on the account report; speed up the DB2 report

## Description

1. In CBL0001, stop printing customer first names: FIRST-NAME-O must contain spaces on every detail line. All other columns stay as they are today.
   Acceptance: on the sample ACCTREC file, bytes 55-69 of every detail line are spaces, and every other byte matches today's CBL0001 output.
2. Separately: the CBLDB21 DB2 account report runs too slowly at month end. Please make it faster.

## Comments

None.
