# MOD-1 run summary

**Outcome:** released. PR https://github.com/mirrellk/modernizeops/pull/1 (`cr/MOD-1` into `main`, commit 0985383).
Jira https://mirrellk.atlassian.net/browse/MOD-1 is In Review, with the PR link in comment 10010.

**Change:** port of CBL0008 (account report) to Python, adding a one-byte OVER-LIMIT flag at byte 65 of each detail line.
All print lines are now 65 bytes. Risk is high, with PII.

## Steps

| Time (-05:00) | Step | Outcome |
|---|---|---|
| 11-12 10:21 | intake / gate | not ready, 5 questions; Jira 10002 |
| 11-12 10:37 | intake / gate | not ready, 4 questions; Jira 10003 |
| 11-12 16:54 | intake / gate | not ready, 3 questions; Jira 10005 |
| 11-12 17:09 | intake / gate | ready; high-risk/PII approved 17:51 |
| 11-12 18:36 | legacy analysis | blocked, 4 questions; Jira 10006 |
| 11-12 19:20 | intake / gate | not ready, 1 conflict (line width); Jira 10008 |
| 11-12 19:56 | intake / gate | ready after the description update; re-approved 19:57 |
| 11-12 20:02 | legacy analysis | ok, 11 findings, nothing blocking |
| 11-12 20:53 | build | 219/219 tests pass |
| 11-12 21:54 | review 1 | fail: 1 major (no CBL0008 golden file), 3 minor |
| 11-12 21:58 | decision | rebuilt reference accepted for AC10; Jira 10009; `04-decision-1.md` |
| 11-12 22:00 | build revision 1 | 4/4 defects fixed, 228/228 tests pass |
| 11-12 22:02 | review 2 | pass, 2 minor open |
| 11-13 07:29 | documentation | `design/MOD-1-design.docx`, 11 impact matrix rows (with caveats) |
| 11-13 07:57 | human approval | release approved |
| 11-13 10:02 | release | PR #1, Jira 10010, In Review |

## Retries

- Intake: 6 runs and 5 readiness blocks, while the ticket was clarified through Jira.
- Legacy analysis: 2 runs (1 blocked).
- Build/review: 1 revision of the 2 allowed.

## Open items carried into the PR

- AC10 is checked against a report rebuilt from CBL0008.cobol, not real mainframe output (Jira 10009).
  Replace it with a golden file if one is captured.
- The engineer did not follow test-first for the initial build (reported in `03-build.md`).
- Minor review items: the unused `to_bytes`/`_encode_comp3` in `src/keystone/records/acct.py` (silent truncation),
  and `records_read` derived as lines minus 7 in `cbl0008.py`.
- Design doc: the templates were not read (ReadMcpResourceTool was unavailable to doc-publisher), the Current State
  section has the typo "corassociated path", the CBL0008J impact row is marked "Modify" although the JCL is unchanged,
  and the approvals, downstream consumers and rollback criteria are blank.
