# MOD-901: Apply a monthly service charge to low-balance accounts

## Description

In CBL0099, subtract a monthly service charge of $2.50 from ACCT-BALANCE for every account whose ACCT-BALANCE is below $100.00, before the balance is printed. Accounts at or above $100.00 are not charged.

Acceptance: on the sample ACCTREC file, a record with ACCT-BALANCE 99.99 prints 97.49 in ACCT-BALANCE-O; a record with ACCT-BALANCE 100.00 prints 100.00 unchanged; all other report columns are unchanged.

## Comments

None.
