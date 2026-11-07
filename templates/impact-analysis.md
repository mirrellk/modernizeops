# Impact analysis for {cr_key}

You are doing the impact analysis for change request {cr_key} against the Keystone Federal Bank
COBOL batch estate. Work only from files and from the keystone-kb tools. Do not work from memory.

## 1. Read the change request

- Read the change request from `runs/{cr_key}/`, which holds the output of the previous pipeline
  step. If that directory is missing or empty, stop and say so. Do not reconstruct the change
  request from memory or from its title.
- Restate the requested change in one or two sentences. Name every field, record, report, file
  and job it mentions, using the exact names from the change request.

## 2. Find what the change touches

Use the keystone-kb tools:

- `list_programs()` gives every PROGRAM-ID, its source path and the copybooks it uses.
- `search_kb(query, kind=...)` takes exact identifiers (field names such as `ACCT-LIMIT`, DD
  names, PROGRAM-IDs) and short descriptions of behaviour. Run several queries. Filter with
  `kind="program"`, `"copybook"`, `"jcl"` or `"standard"` when you know which kind you need.
- `get_source(path, start_line, end_line)` gives the exact lines. Read the lines before you
  claim anything about them, because a search snippet may be cut short.
- Resources: `kb://inventory`, `kb://copybooks/{name}`, `kb://standards/{name}`.

For each item the change touches, follow its dependencies:

1. **Records and copybooks.** Find the record layout that holds each field. If it is in a
   copybook, every program that uses that copybook is affected. Derived copybooks (marked
   "derived" in the inventory) are not `COPY`'d. Each using program has its own inline FD,
   and every one of those FDs must change.
2. **Programs.** List each program that reads, writes, computes or prints the field. Include
   variant programs with a similar but not identical layout, and say how they differ.
3. **JCL.** Find each job step that runs an affected program (`EXEC PGM=`) or compiles it, and
   the DD statements and datasets for the affected files.
4. **Downstream.** Note files and reports that other steps or programs consume.
5. **Standards.** Check `pic-mapping` (PIC to Python types), `coding-standards` (rounding,
   EBCDIC, logging, errors, exit codes) and `data-dictionary` (field meaning, offsets, PII).

## 3. Rules

- Every claim cites `path:start_line-end_line`, the form used in `corpus/standards`.
- Money is `Decimal`, never `float`. State the PIC clause, and the Python type from
  `pic-mapping`, for every numeric field the change touches.
- If the change alters a record length, list every offset and every program that shifts.
- If a business rule is ambiguous or missing (rounding, limits, which accounts are in scope,
  effective dates), do not guess. Record it under Open questions and stop before design.

## 4. Output

Write `runs/{cr_key}/impact-analysis.md` with these sections:

1. **Summary**: the change, in two or three sentences, and the overall risk (low / medium / high)
   with one sentence explaining why.
2. **Impacted programs**: a table of PROGRAM-ID, path, what changes, and citation.
3. **Records and copybooks**: the fields, PICs, offsets and length changes, with citations.
4. **JCL and datasets**: the jobs, steps, DD names and datasets, with citations.
5. **Standards that apply**: each standard and section, and how it constrains the change.
6. **Test impact**: existing tests and test data to update, and new cases needed.
7. **Not impacted**: things that were checked and are not affected, with the reason.
8. **Open questions**: each question needs an answer before design can start. Write "None" if
   there are none.

Then reply with the path of the file you wrote, the overall risk, and the number of open
questions.
