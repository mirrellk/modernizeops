      *----------------------------------------------------------------
      * DERIVED COPYBOOK - extracted by ModernizeOps from inline FD in
      * CBL0001.cobol, CBL0002.cobol, CBL0004.cobol, CBL0005.cobol,
      * CBL0006.cobol, CBL0008.cobol, CBL0009.cobol, CBL0011.cobol,
      * CBL0012.cobol, CBL0033.cobol, CBL006A.cobol, CBLC1.cobol,
      * CBL0106.cbl, CBL0106C.cbl; originals unchanged
      *
      * Record ACCT-FIELDS (170 bytes) of FD ACCT-REC, DD ACCTREC. Code
      * lines copied from CBL0001.cobol lines 42-55 (comment lines
      * omitted). See corpus/standards/data-dictionary.md section 1.
      *----------------------------------------------------------------
       01  ACCT-FIELDS.
           05  ACCT-NO            PIC X(8).
           05  ACCT-LIMIT         PIC S9(7)V99 COMP-3.
           05  ACCT-BALANCE       PIC S9(7)V99 COMP-3.
           05  LAST-NAME          PIC X(20).
           05  FIRST-NAME         PIC X(15).
           05  CLIENT-ADDR.
               10  STREET-ADDR    PIC X(25).
               10  CITY-COUNTY    PIC X(20).
               10  USA-STATE      PIC X(15).
           05  RESERVED           PIC X(7).
           05  COMMENTS           PIC X(50).
