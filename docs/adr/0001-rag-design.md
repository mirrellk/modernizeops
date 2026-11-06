# ADR 0001: Retrieval-augmented generation (RAG) design for the legacy corpus

- **Status:** Accepted
- **Date:** 2026-11-06
- **Deciders:** ModernizeOps maintainers

## Context

ModernizeOps answers questions about, and generates modernized code for, the Keystone Federal Bank COBOL estate in `corpus/legacy/` (COBOL programs, JCL, and derived copybooks) and the standards in `corpus/standards/`. A language model needs the relevant source and standards in its context window. Answers must also cite exact `file:line` locations, the same convention the standards documents use.

Forces:

1. **Structure.** Fixed-size chunks cut paragraphs in half and lose the unit a developer reasons about: a division, a paragraph, a job step, a section of a standard.
2. **Exact identifiers.** Queries often name exact identifiers (field names such as `ACCT-LIMIT`, DD names, program ids). Pure vector search does poorly on these.
3. **Cost and locality.** Embedding should be free and local, and no corpus text should be sent to a hosted API.
4. **Operations.** The store should need no servers to run.
5. **Measurement.** Retrieval quality has to be measured, or it cannot be improved.

## Decision

| Decision | Choice | Why |
|---|---|---|
| Chunking | COBOL: one chunk per DIVISION, and per paragraph inside the PROCEDURE DIVISION. Copybooks whole. JCL: one chunk per EXEC step. Markdown: per heading. | Fixed-size chunks cut paragraphs in half and lose the unit a developer reasons about |
| Metadata | path, kind (program, copybook, jcl, standard), program_id, division, paragraph, start_line, end_line | Enables filters and exact file:line citations |
| Embeddings | Ollama nomic-embed-text, with "search_document: " and "search_query: " prefixes | Free, local, good on code and prose |
| Store | ChromaDB PersistentClient at .rag/chroma, collection keystone_legacy, cosine distance | Zero-ops, file-based |
| Retrieval | Hybrid: vector top 20 + BM25 keyword top 20, merged by reciprocal rank fusion, return top 8 | Exact identifiers such as field names are where pure vector search fails |
| Quality gate | 15 golden queries; hit@5 >= 0.80 | You cannot improve what you do not measure |

### Implementation notes

These details are not in the table. They fill gaps in it and do not change any decision.

- **File kinds.** `.cobol`, `.cbl`, `.cob` → `program`; `.cpy` → `copybook`; `.jcl` → `jcl`; `.md` → `standard`. Extensions match case-insensitively (`.CBL`, `.JCL`). Binary files (a NUL byte, or more than 5% control bytes in the first 8 KB, e.g. EBCDIC or packed datasets) are skipped and reported. Files with any other extension (e.g. `LICENSE`) are skipped and reported.
- **COBOL boundaries.** Divisions are found from their headers. Paragraph and section labels are recognized only in Area A (columns 8–11), and comment lines (indicator `*` or `/` in column 7) are ignored when looking for boundaries. A comment block directly above a boundary belongs to the chunk below it, so a banner comment above IDENTIFICATION DIVISION goes with that division. A bare `PROCEDURE DIVISION.` header with no statements of its own folds into the first paragraph's chunk. If statements come before the first paragraph, the header and those statements form their own chunk with no `paragraph`. Procedure section labels (`X SECTION.`) split the division the same way paragraphs do.
- **JCL boundaries.** The JOB or PROC card and anything else before the first EXEC belong to the first step. `//*` comment lines directly above an EXEC belong to that step. A file with no EXEC is one chunk.
- **Metadata values.** For COBOL, `program_id` is the `PROGRAM-ID`. For a copybook, it is the member name (the file stem, upper-cased). For JCL, `program_id` is the step's `PGM=` value (omitted when the step runs a procedure) and `paragraph` is the step name. For Markdown, `paragraph` is the heading text. Keys with no value are omitted, because Chroma does not store nulls.
- **Ids.** The chunk id is `path:start_line`, with the path repo-relative and in POSIX form. Ids are unique because chunks never overlap. Ingest upserts in batches of 32 and deletes ids that are no longer produced. `--rebuild` drops and recreates the collection first.
- **Indexed text.** Both the embedding and BM25 index each chunk with a one-line context header in front (path, kind, program_id, division, paragraph). The stored document is the chunk text alone.
- **Retrieval.** BM25 is Okapi BM25 (`rank-bm25`). Its tokenizer keeps hyphenated COBOL names whole and also indexes their parts. Reciprocal rank fusion uses `score = Σ 1/(60 + rank)`. The optional `kind` filter applies to both searches.
- **Embedder guard.** The collection records the embedding model it was built with, and the retriever refuses to query it with a different one. Tests use a deterministic `FakeEmbedder` and never contact Ollama.
- **Quality gate.** The golden queries live in `evals/golden_queries.json`. A query is a hit when any of its top 5 results matches one of its expected `{path[, division][, paragraph]}` entries. `python -m rag.evaluate` prints per-query results and exits non-zero below 0.80. The expected answers were written from the source, not from retrieval output.

## Consequences

**Positive**

- Each chunk is a unit a developer reasons about, with an exact `file:line` range for citations.
- BM25 handles exact-identifier queries and vectors handle conceptual ones. RRF fuses them without calibrating their score scales against each other.
- Embedding is local and costs nothing to run, and the store is a directory.
- Changes to chunking or retrieval are measured against a fixed gate, not judged by eye.

**Negative / accepted risks**

- **Chunks are not size-capped.** The table chunks by structure, not size. A whole DATA DIVISION or one long Markdown section can be large. At the time of writing, two chunks are longer than nomic-embed-text's 2,048-token context: `corpus/legacy/INVENTORY.md:1` (that file has one heading) and the data dictionary's Appendix A. Ollama truncates them when embedding, so the tail of each is reachable only through BM25. All COBOL DATA DIVISION chunks currently fit (the largest is about 1,400 tokens).
- **Mixed `standard` kind.** All Markdown is kind `standard`, including `corpus/legacy/INVENTORY.md`, which is a derived inventory and not a standard. A `kind="standard"` filter returns it too.
- **Near-duplicate chunks.** The course corpus contains many near-identical programs, so whole-division chunks of their DATA DIVISIONs are near duplicates. They can crowd one another out of the top 5.
- **Callers outrank definitions.** Every compile job contains `EXEC IGYWCL`, so a query about a procedure can rank its callers above its definition.
- **Ids move with edits.** An id depends on its start line, so editing a file above a chunk changes that chunk's id. Stale-id cleanup keeps the index correct, but saved citations can go stale.
- **BM25 is rebuilt per process.** That is fine at hundreds of chunks. It should be persisted once the corpus is much larger.
- **Re-embedding cost.** Changing the embedding model requires `--rebuild`. The embedder guard makes a mismatch fail loudly.
