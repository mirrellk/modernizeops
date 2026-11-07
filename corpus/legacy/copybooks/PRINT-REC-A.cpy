      *----------------------------------------------------------------
      * DERIVED COPYBOOK - extracted by ModernizeOps from inline FD in
      * CBL0001.cobol, CBL0002.cobol, CBL0033.cobol; originals unchanged
      *
      * Record PRINT-REC (119 bytes) of FD PRINT-LINE, DD PRTLINE. Code
      * lines copied from CBL0001.cobol lines 28-37 (comment lines
      * omitted). See corpus/standards/data-dictionary.md section 2.1
      * (Layout A).
      *----------------------------------------------------------------
       01  PRINT-REC.
           05  ACCT-NO-O      PIC X(8).
           05  ACCT-LIMIT-O   PIC $$,$$$,$$9.99.
           05  ACCT-BALANCE-O PIC $$,$$$,$$9.99.
           05  LAST-NAME-O    PIC X(20).
           05  FIRST-NAME-O   PIC X(15).
           05  COMMENTS-O     PIC X(50).
