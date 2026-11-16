# CR intake golden set

Synthetic change-request tickets for `scripts/eval_intake.py`, which runs the cr-intake agent
headless on each `<name>.md` (in place of Jira) and scores the brief against `<name>.expected.json`.

| Case | Key | Source | Expected |
|---|---|---|---|
| `mod-1` | MOD-1 | Jira description, 2026-11-15 (comments omitted; the description supersedes them) | ready |
| `mod-2` | MOD-2 | Jira description, 2026-11-15 | not ready: which report, subtotal layout / grand total |
| `mod-3` | MOD-3 | Jira description, 2026-11-15 | not ready: cr-brief Example 2 |
| `mod-4` | MOD-4 | Jira description, 2026-11-15 | not ready: mask format; CBL0006 maps to two sources |
| `mod-5` | MOD-5 | Jira description, 2026-11-15 | not ready: nothing specified |
| `edge-unknown-program` | MOD-901 | synthetic | not ready: CBL0099 is not in INVENTORY.md |
| `edge-mixed-requests` | MOD-902 | synthetic | not ready: second, unrelated request has no acceptance |
| `edge-no-program` | MOD-903 | synthetic | not ready: acceptance given, program not named |

Expected files hold `cr_key`, `ready`, `risk`, `pii`, `programs`, `min_missing_questions`
(a floor on `missing_information` items) and a `rationale` that cites the cr-brief escalation
criteria. Only the first six fields are scored. The MOD-1..MOD-5 copies are frozen: if a Jira
ticket changes later, update the copy and its expected file together.
