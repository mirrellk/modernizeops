"""keystone-kb: MCP server over the Keystone Federal Bank legacy knowledge base.

    uv run python -m mcp_servers.kb_server.server        # stdio transport

Tools: search_kb, get_source, list_programs and inspect_account_file. Resources: kb://standards/{name},
kb://copybooks/{name} and kb://inventory. Prompt: impact_analysis.

Built on the mcp 2.x ``MCPServer``, which replaced v1's ``FastMCP``.

Every anticipated tool failure raises ``ToolError`` whose message is JSON:
``{"error_category", "retryable", "message", "suggestion"}``, where error_category is one of
not_found, invalid_input or backend_unavailable.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, NoReturn, TypedDict

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError, UnexpectedToolError
from mcp_types import CallToolResult, TextContent
from pydantic import ValidationError

from rag.ingest import is_binary
from rag.store import REPO_ROOT, EmbedderMismatchError

CORPUS = REPO_ROOT / "corpus"
STANDARDS_DIR = CORPUS / "standards"
COPYBOOKS_DIR = CORPUS / "legacy" / "copybooks"
INVENTORY = CORPUS / "legacy" / "INVENTORY.md"
IMPACT_TEMPLATE = REPO_ROOT / "templates" / "impact-analysis.md"

SNIPPET_LINES = 40
MAX_K = 20
MAX_SOURCE_LINES = 500
CR_KEY = re.compile(r"MOD-[1-9][0-9]*")
INGEST_CMD = "uv run python -m rag.ingest --rebuild"

Kind = Literal["program", "copybook", "jcl", "standard"]
KINDS: tuple[str, ...] = ("program", "copybook", "jcl", "standard")
ErrorCategory = Literal["not_found", "invalid_input", "backend_unavailable"]


class SearchHit(TypedDict):
    path: str
    start_line: int
    end_line: int
    program_id: str | None
    paragraph: str | None
    score: float
    snippet: str


class SourceLines(TypedDict):
    path: str
    start_line: int
    end_line: int
    total_lines: int
    text: str


class CopybookRef(TypedDict):
    name: str
    path: str | None
    derived: bool


class ProgramEntry(TypedDict):
    program_id: str
    path: str
    copybooks: list[CopybookRef]


class KBServer(MCPServer):
    """MCPServer whose tool errors always reach the client as the bare JSON error body.

    The SDK prefixes a ToolError's text with "Error executing tool <name>: " and reports
    argument-schema failures and crashes as free text. This rewrites all of them into the
    {"error_category", "retryable", "message", "suggestion"} shape, keeping the exception type
    (so the SDK still logs crashes with their traceback).
    """

    async def call_tool(self, name, arguments, context=None):
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as exc:
            raise type(exc)(json.dumps(normalize_tool_error(name, exc))) from exc


def normalize_tool_error(name: str, exc: ToolError) -> dict:
    text = str(exc).removeprefix(f"Error executing tool {name}: ")
    try:
        body = json.loads(text)
    except ValueError:
        body = None
    if isinstance(body, dict) and "error_category" in body:
        return body
    if isinstance(exc.__cause__, ValidationError):
        problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}"
                             for e in exc.__cause__.errors())
        return {"error_category": "invalid_input", "retryable": False,
                "message": f"Invalid arguments for {name}: {problems}",
                "suggestion": "Fix the arguments to match the tool's input schema."}
    if text.startswith("Unknown tool"):
        return {"error_category": "not_found", "retryable": False, "message": text,
                "suggestion": "Use search_kb, get_source, list_programs or inspect_account_file."}
    kind = "an unexpected internal error" if isinstance(exc, UnexpectedToolError) else text
    return {"error_category": "backend_unavailable", "retryable": False,
            "message": f"{name} failed with {kind}.",
            "suggestion": "Retry once; if it fails again, check the keystone-kb server log."}


mcp = KBServer(
    "keystone-kb",
    instructions=(
        "Knowledge base for Keystone Federal Bank's COBOL batch estate: COBOL programs, derived "
        "copybooks and JCL in corpus/legacy, and the bank's standards in corpus/standards. "
        "Use search_kb to find code, then get_source to read exact lines before you cite "
        "path:start-end. Use list_programs for the program inventory. Use inspect_account_file "
        "to summarize an ACCTREC data file (record count, totals, below/equal/above limit)."
    ),
)


# --------------------------------------------------------------------------- errors


def tool_error(category: ErrorCategory, message: str, suggestion: str, *, retryable: bool = False) -> ToolError:
    body = {"error_category": category, "retryable": retryable, "message": message, "suggestion": suggestion}
    return ToolError(json.dumps(body))


def _fail(category: ErrorCategory, message: str, suggestion: str, *, retryable: bool = False) -> NoReturn:
    raise tool_error(category, message, suggestion, retryable=retryable)


def _backend_error(exc: Exception) -> ToolError:
    """Map a failure in the embedder or the vector store to a backend_unavailable ToolError."""
    import chromadb.errors
    import ollama

    if isinstance(exc, ConnectionError | httpx.TransportError):
        return tool_error(
            "backend_unavailable", f"Ollama embedding server is unreachable: {exc}",
            "Start Ollama (`ollama serve`) or check OLLAMA_HOST, then retry.", retryable=True)
    if isinstance(exc, ollama.ResponseError):
        if exc.status_code == 404:
            return tool_error(
                "backend_unavailable", f"Ollama does not have the embedding model: {exc.error}",
                "Run `ollama pull nomic-embed-text`, then retry.")
        return tool_error(
            "backend_unavailable", f"Ollama returned an error: {exc.error} (status {exc.status_code})",
            "Retry shortly; if it persists, check the Ollama server log.", retryable=True)
    if isinstance(exc, chromadb.errors.NotFoundError):
        return tool_error(
            "backend_unavailable", "The knowledge-base index has not been built.",
            f"Run `{INGEST_CMD}`.")
    if isinstance(exc, EmbedderMismatchError):
        return tool_error("backend_unavailable", str(exc), f"Run `{INGEST_CMD}`.")
    return tool_error(
        "backend_unavailable", f"Search backend failed: {type(exc).__name__}: {exc}",
        f"Check that Ollama is running and the index is built (`{INGEST_CMD}`).")


# --------------------------------------------------------------------------- retriever

_retriever = None


def set_retriever(retriever) -> None:
    """Use ``retriever`` (anything with ``retrieve(query, k, kind)``) for search_kb; None resets."""
    global _retriever
    _retriever = retriever


def get_retriever():
    global _retriever
    if _retriever is None:
        from rag.retriever import _default_retriever

        _retriever = _default_retriever()
    return _retriever


# --------------------------------------------------------------------------- tools


@mcp.tool()
def search_kb(
    query: str, kind: Kind | None = None, k: int = 8
) -> Annotated[CallToolResult, list[SearchHit]]:
    """Search the Keystone legacy knowledge base: COBOL programs, copybooks, JCL and standards.

    Use this first, to find where something is defined or used. It works for exact identifiers
    (field names like ACCT-LIMIT, DD names like ACCTREC, PROGRAM-IDs like CBL0001) and for
    plain-language questions ("which job runs the account report?"). It is a hybrid search:
    keyword (BM25) plus vector, fused by reciprocal rank fusion.

    Do NOT use it to read a whole file or exact line ranges; use get_source for that. Do NOT
    use it to list all programs; use list_programs.

    Args:
        query: identifiers and/or a short description of what you are looking for.
        kind: limit results to one kind: "program" (COBOL source), "copybook" (record layouts),
            "jcl" (job steps) or "standard" (bank standards and the inventory). Omit to search all.
        k: number of results, 1-20 (default 8).

    Returns a list, best first, of {path, start_line, end_line, program_id, paragraph, score,
    snippet}. Each result is one chunk: a COBOL division or PROCEDURE paragraph, a whole
    copybook, a JCL EXEC step, or a Markdown section. path is repo-relative
    (corpus/legacy/...); start_line and end_line are 1-based and inclusive; program_id and
    paragraph may be null; score is the fused rank score (higher is better, comparable only
    within one call). snippet holds at most the first 40 lines of the chunk; when
    end_line - start_line + 1 > 40, call get_source for the rest. No match returns [] with a
    note; that is not an error.
    """
    if not isinstance(query, str) or not query.strip():
        _fail("invalid_input", "query must be a non-empty string.",
              "Pass identifiers such as ACCT-LIMIT or a short question.")
    if kind is not None and kind not in KINDS:
        _fail("invalid_input", f"kind must be one of {', '.join(KINDS)} or null, not {kind!r}.",
              "Omit kind to search every kind.")
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= MAX_K:
        _fail("invalid_input", f"k must be an integer from 1 to {MAX_K}, not {k!r}.", "Use the default k=8.")
    try:
        results = get_retriever().retrieve(query, k=k, kind=kind)
    except Exception as exc:  # any backend failure becomes a structured ToolError
        raise _backend_error(exc) from exc

    hits: list[SearchHit] = []
    for r in results:
        m = r.metadata
        hits.append(SearchHit(
            path=m["path"], start_line=int(m["start_line"]), end_line=int(m["end_line"]),
            program_id=m.get("program_id"), paragraph=m.get("paragraph"), score=round(float(r.score), 6),
            snippet="\n".join(r.text.splitlines()[:SNIPPET_LINES]),
        ))
    if not hits:
        scope = f" of kind {kind!r}" if kind else ""
        note = (f"No results{scope} for {query!r}. This is not an error. Try other identifiers, "
                "a broader description" + (", or drop the kind filter." if kind else "."))
        return CallToolResult(content=[TextContent(text="[]"), TextContent(text=note)],
                              structured_content={"result": []})
    return CallToolResult(content=[TextContent(text=json.dumps(hits, indent=1))],
                          structured_content={"result": hits})


def _resolve_corpus_path(path: str) -> Path:
    if not isinstance(path, str) or not path.strip() or "\x00" in path:
        _fail("invalid_input", "path must be a non-empty string.",
              "Pass a repo-relative path from search_kb, e.g. corpus/legacy/....")
    candidate = (REPO_ROOT / path.strip().replace("\\", "/")).resolve()
    if not candidate.is_relative_to(CORPUS.resolve()):
        _fail("invalid_input", f"{path!r} is outside corpus/; only corpus files can be read.",
              "Pass a repo-relative path under corpus/, as returned by search_kb or list_programs.")
    if not candidate.is_file():
        _fail("not_found", f"No file at {path!r}.",
              "Use a path exactly as returned by search_kb or list_programs.")
    return candidate


@mcp.tool()
def get_source(path: str, start_line: int, end_line: int) -> SourceLines:
    """Return exact source lines from a corpus file, for reading and citing code precisely.

    Use it after search_kb or list_programs, to read a chunk in full (search snippets stop at
    40 lines), to see the context around a hit, or to quote lines verbatim for a
    path:start-end citation.

    Do NOT use it to find code; use search_kb. Only files under corpus/ can be read. Paths
    outside it, and binary data files, are refused.

    Args:
        path: repo-relative path, e.g. "corpus/legacy/COBOL Programming Course #2 - Learning
            COBOL/Labs/cbl/CBL0001.cobol" (as returned by search_kb).
        start_line: first line, 1-based.
        end_line: last line, inclusive; at most 500 lines per call.

    Returns {path, start_line, end_line, total_lines, text}. text is the requested lines
    exactly as in the file (no line numbers added), joined with "\\n". total_lines is the
    file's length, so you can page through it.
    """
    file = _resolve_corpus_path(path)
    for name, value in (("start_line", start_line), ("end_line", end_line)):
        if isinstance(value, bool) or not isinstance(value, int):
            _fail("invalid_input", f"{name} must be an integer, not {value!r}.", "Use 1-based line numbers.")
    data = file.read_bytes()
    if is_binary(data):
        _fail("invalid_input", f"{path!r} is a binary data file, not source.",
              "Read COBOL, copybook, JCL or Markdown files only.")
    lines = data.decode("utf-8", errors="replace").splitlines()
    total = len(lines)
    if start_line < 1 or end_line < start_line:
        _fail("invalid_input", f"Need 1 <= start_line <= end_line; got {start_line}-{end_line}.",
              f"The file has {total} lines.")
    if start_line > total:
        _fail("invalid_input", f"start_line {start_line} is past the end of the file ({total} lines).",
              f"Use a range within 1-{total}.")
    if end_line > total:
        _fail("invalid_input", f"end_line {end_line} is past the end of the file ({total} lines).",
              f"Use end_line={total} or less.")
    if end_line - start_line + 1 > MAX_SOURCE_LINES:
        _fail("invalid_input", f"At most {MAX_SOURCE_LINES} lines per call; asked for "
              f"{end_line - start_line + 1}.", f"Page through it, e.g. {start_line}-{start_line + MAX_SOURCE_LINES - 1}.")
    rel = file.relative_to(REPO_ROOT.resolve()).as_posix()
    return SourceLines(path=rel, start_line=start_line, end_line=end_line, total_lines=total,
                       text="\n".join(lines[start_line - 1:end_line]))


# --------------------------------------------------------------------------- account files

# Derived copybook ACCT-FIELDS (corpus/legacy/copybooks/ACCT-FIELDS.cpy): (name, length, kind).
ACCT_FIELDS: tuple[tuple[str, int, str], ...] = (
    ("ACCT-NO", 8, "X"), ("ACCT-LIMIT", 5, "COMP-3"), ("ACCT-BALANCE", 5, "COMP-3"),
    ("LAST-NAME", 20, "X"), ("FIRST-NAME", 15, "X"), ("STREET-ADDR", 25, "X"),
    ("CITY-COUNTY", 20, "X"), ("USA-STATE", 15, "X"), ("RESERVED", 7, "X"), ("COMMENTS", 50, "X"),
)
ACCT_RECORD_LENGTH = 170
assert sum(length for _, length, _ in ACCT_FIELDS) == ACCT_RECORD_LENGTH
ACCT_MONEY_SCALE = 2  # S9(7)V99
MAX_ACCOUNT_FILE_BYTES = 10 * 1024 * 1024
SAMPLES_PER_CATEGORY = 3

Category = Literal["below", "equal", "above"]


class AccountSample(TypedDict):
    record_no: int
    acct_no_masked: str
    limit: str
    balance: str
    category: Category


class AccountFileSummary(TypedDict):
    path: str
    record_length: int
    record_count: int
    tlimit: str
    tbalance: str
    below: int
    equal: int
    above: int
    sample_records: list[AccountSample]


class InvalidNumericDataError(ValueError):
    """Invalid packed-decimal data (the S0C7 equivalent). Carries no field contents."""


def unpack_comp3(raw: bytes, scale: int) -> Decimal:
    """Decode COMP-3: two digits per byte, last nibble the sign (C/F = +, D = -); else raise."""
    nibbles = raw.hex().upper()
    digits, sign = nibbles[:-1], nibbles[-1]
    if not digits.isdigit() or sign not in "CDF":
        raise InvalidNumericDataError("invalid packed-decimal nibble")
    value = Decimal(int(digits)).scaleb(-scale)
    return -value if sign == "D" else value


def _mask_acct_no(raw: bytes) -> str:
    text = raw.decode("cp037").strip()
    return "****" + text[-4:] if text else "****"


@mcp.tool()
def inspect_account_file(path: str) -> AccountFileSummary:
    """Decode a fixed-length EBCDIC ACCT-FIELDS data file (DD ACCTREC) and summarize it, PII-safe.

    Use it to check a sample account file read by the account-report programs: its record
    length and count, the exact totals of ACCT-LIMIT and ACCT-BALANCE (what TLIMIT/TBALANCE
    style accumulators should print), and which records have a balance below, equal to or above
    their limit, for choosing test records.

    Do NOT use it on source code (use get_source) or on files with another layout: it assumes the
    170-byte ACCT-FIELDS record of corpus/legacy/copybooks/ACCT-FIELDS.cpy (cp037 text, ACCT-LIMIT
    and ACCT-BALANCE as S9(7)V99 COMP-3). Only files under corpus/ can be read. Names, addresses
    and comments are never returned.

    Args:
        path: repo-relative path under corpus/, e.g. "corpus/legacy/COBOL Programming Course #2 -
            Learning COBOL/Labs/data/data".

    Returns {path, record_length, record_count, tlimit, tbalance, below, equal, above,
    sample_records}. Money values are exact decimal strings (e.g. "1234.50"). below/equal/above
    count records by ACCT-BALANCE vs ACCT-LIMIT. sample_records lists up to 3 records per
    category as {record_no (1-based), acct_no_masked (last 4 digits only), limit, balance,
    category}. A file whose size is not a multiple of 170, or with invalid packed data, is
    refused with the record number and field name.
    """
    file = _resolve_corpus_path(path)
    size = file.stat().st_size
    if size > MAX_ACCOUNT_FILE_BYTES:
        _fail("invalid_input", f"{path!r} is {size} bytes; the limit is {MAX_ACCOUNT_FILE_BYTES}.",
              "Inspect a smaller sample file.")
    data = file.read_bytes()
    if not data or len(data) % ACCT_RECORD_LENGTH:
        _fail("invalid_input",
              f"{path!r} is {len(data)} bytes, not a positive multiple of the {ACCT_RECORD_LENGTH}-byte "
              "ACCT-FIELDS record.",
              "Check that this is an ACCTREC data file transferred in binary, not text mode.")

    offsets: dict[str, tuple[int, int]] = {}
    pos = 0
    for name, length, _ in ACCT_FIELDS:
        offsets[name] = (pos, pos + length)
        pos += length

    tlimit = tbalance = Decimal(0)
    counts: dict[Category, int] = {"below": 0, "equal": 0, "above": 0}
    samples: list[AccountSample] = []
    for record_no, start in enumerate(range(0, len(data), ACCT_RECORD_LENGTH), start=1):
        record = data[start:start + ACCT_RECORD_LENGTH]
        values: dict[str, Decimal] = {}
        for name in ("ACCT-LIMIT", "ACCT-BALANCE"):
            lo, hi = offsets[name]
            try:
                values[name] = unpack_comp3(record[lo:hi], ACCT_MONEY_SCALE)
            except InvalidNumericDataError:
                _fail("invalid_input",
                      f"Record {record_no}, field {name} (bytes {lo + 1}-{hi}): invalid packed-decimal data.",
                      "Check the file is an ACCT-FIELDS file transferred in binary.")
        limit, balance = values["ACCT-LIMIT"], values["ACCT-BALANCE"]
        tlimit += limit
        tbalance += balance
        category: Category = "below" if balance < limit else "equal" if balance == limit else "above"
        counts[category] += 1
        if counts[category] <= SAMPLES_PER_CATEGORY:
            lo, hi = offsets["ACCT-NO"]
            samples.append(AccountSample(
                record_no=record_no, acct_no_masked=_mask_acct_no(record[lo:hi]),
                limit=str(limit), balance=str(balance), category=category))

    rel = file.relative_to(REPO_ROOT.resolve()).as_posix()
    return AccountFileSummary(
        path=rel, record_length=ACCT_RECORD_LENGTH, record_count=len(data) // ACCT_RECORD_LENGTH,
        tlimit=str(tlimit), tbalance=str(tbalance), sample_records=samples, **counts)


_ROW = re.compile(r"^\|(?P<cells>.+)\|\s*$")
_CODE = re.compile(r"`([^`]+)`(\s*\(derived\))?")


def parse_inventory(text: str) -> list[ProgramEntry]:
    """Rows of the INVENTORY.md program table: PROGRAM-ID, source path and copybooks."""
    programs: list[ProgramEntry] = []
    in_table = False
    for line in text.splitlines():
        m = _ROW.match(line.strip())
        if not m:
            in_table = False
            continue
        cells = [c.strip() for c in m["cells"].split("|")]
        if cells[:2] == ["PROGRAM-ID", "Source"]:
            in_table = True
            continue
        if not in_table or set(cells[0]) <= {"-", ":"} or len(cells) < 4:
            continue
        copybooks: list[CopybookRef] = []
        for name, derived in _CODE.findall(cells[3]):
            is_path = name.endswith(".cpy")
            copybooks.append(CopybookRef(
                name=Path(name).stem if is_path else name,
                path=f"corpus/legacy/{name}" if is_path else None,
                derived=bool(derived),
            ))
        programs.append(ProgramEntry(program_id=cells[0], path=f"corpus/legacy/{cells[1]}",
                                     copybooks=copybooks))
    return programs


@mcp.tool()
def list_programs() -> list[ProgramEntry]:
    """List every COBOL program in the legacy estate, with its source path and copybooks.

    Use it for an overview of the estate, to map a PROGRAM-ID to its file, or to find every
    program that uses a copybook (the starting point of an impact analysis). It reads
    corpus/legacy/INVENTORY.md, which was built from the source.

    Do NOT use it to find where a field or paragraph is used; use search_kb. It does not
    return JCL; use search_kb with kind="jcl".

    Returns a list of {program_id, path, copybooks}. path is repo-relative and can be passed
    to get_source. copybooks is a list of {name, path, derived}: path is the copybook file
    (null for a system include such as SQLCA), and derived=true means the copybook was
    extracted from an identical inline FD; the program does not COPY it. Note that two files
    declare PROGRAM-ID CBL0006 (CBL0006.cobol and CBLC1.cobol); path tells them apart.
    """
    if not INVENTORY.is_file():
        _fail("not_found", "corpus/legacy/INVENTORY.md is missing.",
              "Restore the inventory, or use search_kb with kind='program'.")
    programs = parse_inventory(INVENTORY.read_text(encoding="utf-8"))
    if not programs:
        _fail("not_found", "INVENTORY.md has no program table.",
              "Use search_kb with kind='program'.")
    return programs


# --------------------------------------------------------------------------- resources


def _named_file(directory: Path, name: str, suffix: str, what: str) -> Path:
    """Match ``name`` (with or without suffix, any case) against the files in ``directory``."""
    files = sorted(directory.glob(f"*{suffix}"))
    wanted = name.strip().lower().removesuffix(suffix)
    for f in files:
        if f.stem.lower() == wanted:
            return f
    available = ", ".join(f.stem for f in files) or "none"
    body = {"error_category": "not_found", "retryable": False, "message": f"No {what} named {name!r}.",
            "suggestion": f"Available: {available}."}
    raise ResourceNotFoundError(json.dumps(body))


def _names(directory: Path, suffix: str) -> str:
    return ", ".join(f.stem for f in sorted(directory.glob(f"*{suffix}"))) or "none"


@mcp.resource("kb://standards/{name}", mime_type="text/markdown",
              description=f"A Keystone Federal Bank standard (Markdown). Names: {_names(STANDARDS_DIR, '.md')}.")
def standard(name: str) -> str:
    return _named_file(STANDARDS_DIR, name, ".md", "standard").read_text(encoding="utf-8")


@mcp.resource("kb://copybooks/{name}", mime_type="text/plain",
              description="A copybook's COBOL text (derived copybooks are extracted from inline FDs). "
                          f"Names: {_names(COPYBOOKS_DIR, '.cpy')}.")
def copybook(name: str) -> str:
    return _named_file(COPYBOOKS_DIR, name, ".cpy", "copybook").read_text(encoding="utf-8")


@mcp.resource("kb://inventory", mime_type="text/markdown",
              description="corpus/legacy/INVENTORY.md: every program with its files and copybooks.")
def inventory() -> str:
    if not INVENTORY.is_file():
        raise ResourceNotFoundError(json.dumps({
            "error_category": "not_found", "retryable": False,
            "message": "corpus/legacy/INVENTORY.md is missing.", "suggestion": "Restore the inventory."}))
    return INVENTORY.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- prompts


@mcp.prompt()
def impact_analysis(cr_key: str) -> str:
    """Standard impact-analysis instructions for a MOD change request (e.g. MOD-123)."""
    key = cr_key.strip().upper() if isinstance(cr_key, str) else ""
    if not CR_KEY.fullmatch(key):
        raise ValueError(f"cr_key must be a Jira MOD key such as MOD-123, not {cr_key!r}")
    return IMPACT_TEMPLATE.read_text(encoding="utf-8").replace("{cr_key}", key)


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
