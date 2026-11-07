      *----------------------------------------------------------------
      * DERIVED COPYBOOK - extracted by ModernizeOps from inline FD in
      * CBL0004.cobol, CBL0006.cobol, CBL0007.cobol, CBL0008.cobol,
      * CBL0009.cobol, CBL0010.cobol, CBL0011.cobol, CBL0012.cobol,
      * CBL006A.cobol, CBLC1.cobol, CBL0106.cbl, CBL0106C.cbl; originals
      * unchanged
      *
      * Record PRINT-REC (62 bytes) of FD PRINT-LINE, DD PRTLINE. Code
      * lines copied from CBL0004.cobol lines 24-42 (comment lines
      * omitted). See corpus/standards/data-dictionary.md section 2.2
      * (Layout B).
      *----------------------------------------------------------------
       01  PRINT-REC.
           05  ACCT-NO-O      PIC X(8).
           05  FILLER         PIC X(02) VALUE SPACES.
           05  LAST-NAME-O    PIC X(20).
           05  FILLER         PIC X(02) VALUE SPACES.
           05  ACCT-LIMIT-O   PIC $$,$$$,$$9.99.
           05  FILLER         PIC X(02) VALUE SPACES.
           05  ACCT-BALANCE-O PIC $$,$$$,$$9.99.
           05  FILLER         PIC X(02) VALUE SPACES.
