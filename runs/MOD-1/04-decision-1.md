# MOD-1 decision after review 1

Source: user decision in the process-cr session, 2026-11-12; recorded on Jira as comment 10009.

AC10 (byte-for-byte equality with CBL0008 output): no legacy CBL0008 golden file exists. The business accepts an
expected report rebuilt from CBL0008.cobol as the reference for AC10 in this release. The comparison must be made on
the encoded output bytes the module writes, not on str lines, and the test must cite this decision (Jira MOD-1 comment
10009). A real CBL0008 golden file, if captured later, replaces the rebuilt reference.
