      *----------------------------------------------------------------
      * DERIVED COPYBOOK - extracted by ModernizeOps from inline FD in
      * CBLDB21.cbl, CBLDB22.cbl; originals unchanged
      *
      * Record REPREC (119 bytes) of FD REPOUT, DD UT-S-REPORT. Code
      * lines copied from CBLDB21.cbl lines 26-32 (comment lines
      * omitted). See corpus/standards/data-dictionary.md section 5.1.
      *----------------------------------------------------------------
       01  REPREC.
           05  ACCT-NO-O      PIC X(8).
           05  ACCT-LIMIT-O   PIC $$,$$$,$$9.99.
           05  ACCT-BALANCE-O PIC $$,$$$,$$9.99.
           05  ACCT-LASTN-O   PIC X(20).
           05  ACCT-FIRSTN-O  PIC X(15).
           05  ACCT-COMMENT-O PIC X(50).
