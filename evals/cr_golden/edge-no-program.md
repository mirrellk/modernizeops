# MOD-903: Print negative balances with a trailing CR

## Description

On the account report, negative balances must print with a trailing CR sign instead of with no sign.

Acceptance: a record with ACCT-BALANCE -125.50 prints "$125.50CR" in ACCT-BALANCE-O, right-aligned in the column; a record with ACCT-BALANCE 125.50 prints "$125.50" followed by two spaces; all other columns are unchanged.

## Comments

None.
