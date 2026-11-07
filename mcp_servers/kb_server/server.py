"""keystone-kb: MCP server over the Keystone Federal Bank legacy knowledge base.

    uv run python -m mcp_servers.kb_server.server        # stdio transport

Tools: search_kb, get_source and list_programs. Resources: kb://standards/{name},
kb://copybooks/{name} and kb://inventory. Prompt: impact_analysis.

Built on the mcp 2.x ``MCPServer``, which replaced v1's ``FastMCP``.

Every anticipated tool failure raises ``ToolError`` whose message is JSON:
``{"error_category", "retryable", "message", "suggestion"}``, where error_category is one of
not_found, invalid_input or backend_unavailable.
"""

from __future__ import annotations

import json
import re
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
                "suggestion": "Use search_kb, get_source or list_programs."}
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
        "path:start-end. Use list_programs for the program inventory."
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
