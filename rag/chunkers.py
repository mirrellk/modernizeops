"""Structure-aware chunkers (see docs/adr/0001-rag-design.md).

- program  (COBOL ``.cobol``/``.cbl``/``.cob``, any case): one chunk per DIVISION, except the
  PROCEDURE DIVISION, which gets one chunk per paragraph (or section label).
- copybook (``.cpy``): the whole file is one chunk.
- jcl      (``.jcl``, any case): one chunk per EXEC step.
- standard (``.md``): one chunk per heading.

Every chunk's metadata uses only these keys: path, kind, program_id, division, paragraph,
start_line, end_line. Keys with no value for a chunk are omitted (Chroma does not store None).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

KIND_BY_SUFFIX = {
    ".cobol": "program",
    ".cbl": "program",
    ".cob": "program",
    ".cpy": "copybook",
    ".jcl": "jcl",
    ".md": "standard",
}
KINDS = ("program", "copybook", "jcl", "standard")
METADATA_KEYS = ("path", "kind", "program_id", "division", "paragraph", "start_line", "end_line")


@dataclass(frozen=True)
class Chunk:
    text: str
    metadata: dict[str, str | int] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.metadata['path']}:{self.metadata['start_line']}"


def kind_for(path: str | Path) -> str | None:
    return KIND_BY_SUFFIX.get(Path(path).suffix.lower())


def chunk_text(text: str, path: str, kind: str | None = None) -> list[Chunk]:
    """Chunk ``text`` from ``path`` using the chunker for ``kind`` (inferred from the suffix)."""
    kind = kind or kind_for(path)
    chunker = CHUNKERS.get(kind or "")
    if chunker is None:
        raise ValueError(f"no chunker for {path!r} (kind={kind!r})")
    return chunker(text, path)


def _make(lines: list[str], start: int, end: int, **meta: str | int | None) -> Chunk | None:
    """Build a chunk from 0-based ``lines[start:end]``; None if it holds only blank lines."""
    body = "\n".join(lines[start:end]).strip("\n")
    if not body.strip():
        return None
    meta = {**meta, "start_line": start + 1, "end_line": end}
    return Chunk(body, {k: meta[k] for k in METADATA_KEYS if meta.get(k) not in (None, "")})


def _spans(starts: list[int], total: int) -> list[tuple[int, int]]:
    return [(s, starts[i + 1] if i + 1 < len(starts) else total) for i, s in enumerate(starts)]


# --------------------------------------------------------------------------- COBOL


def _is_comment(line: str) -> bool:
    return len(line) > 6 and line[6] in "*/"


def _code(line: str) -> str:
    """Program text (columns 8-72) of a fixed-format line, upper-cased."""
    return line[7:72].upper() if len(line) > 7 else ""


def _area_a(line: str) -> bool:
    return len(line) > 7 and line[7] != " "


_DIVISION = re.compile(r"^\s*(IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b")
_PARAGRAPH = re.compile(r"^([A-Z0-9][\w-]*(?:\s+SECTION)?)\s*\.\s*$")
_PROGRAM_ID = re.compile(r"PROGRAM-ID\.?\s+'?([\w#@$-]+)")


def _program_id(lines: list[str]) -> str | None:
    for line in lines:
        if not _is_comment(line) and (m := _PROGRAM_ID.search(_code(line))):
            return m.group(1)
    return None


def _attach_comments(lines: list[str], i: int, floor: int) -> int:
    """Move a boundary up over the comment block directly above it (not past ``floor``)."""
    while i > floor and _is_comment(lines[i - 1]):
        i -= 1
    return i


def _has_code(lines: list[str], start: int, end: int, skip_first: bool = False) -> bool:
    rows = lines[start:end]
    code = [x for x in rows if not _is_comment(x) and _code(x).strip()]
    return len(code) > (1 if skip_first else 0)


def chunk_cobol(text: str, path: str) -> list[Chunk]:
    lines = text.splitlines()
    program_id = _program_id(lines)

    # (start, division, paragraph): division boundaries, then paragraph labels in PROCEDURE.
    bounds: list[tuple[int, str | None, str | None]] = []
    division: str | None = None
    for i, line in enumerate(lines):
        if _is_comment(line) or not (code := _code(line)).strip():
            continue
        if m := _DIVISION.match(code):
            division = "IDENTIFICATION" if m.group(1) == "ID" else m.group(1)
            bounds.append((i, division, None))
        elif division == "PROCEDURE" and _area_a(line) and (m := _PARAGRAPH.match(code.strip())):
            bounds.append((i, division, m.group(1)))

    # Leading comment blocks belong to the chunk that follows them.
    floor = 0
    starts = []
    for i, div, para in bounds:
        s = _attach_comments(lines, i, floor)
        starts.append((s, div, para))
        floor = i + 1
    if not starts or starts[0][0] > 0:
        if starts and not _has_code(lines, 0, starts[0][0]):
            starts[0] = (0, *starts[0][1:])  # banner comments before IDENTIFICATION
        else:
            starts.insert(0, (0, None, None))

    spans = _spans([s for s, _, _ in starts], len(lines))
    chunks: list[Chunk] = []
    carry: int | None = None  # start of a PROCEDURE DIVISION header with no code of its own
    for (start, end), (_, div, para) in zip(spans, starts, strict=True):
        if div == "PROCEDURE" and para is None and not _has_code(lines, start, end, skip_first=True):
            nxt = next((p for s, d, p in starts if s >= end and d == "PROCEDURE"), None)
            if nxt is not None:
                carry = start
                continue
        if carry is not None:
            start, carry = carry, None
        chunk = _make(lines, start, end, path=path, kind="program", program_id=program_id,
                      division=div, paragraph=para)
        if chunk:
            chunks.append(chunk)
    return chunks


# --------------------------------------------------------------------------- copybook


def chunk_copybook(text: str, path: str) -> list[Chunk]:
    lines = text.splitlines()
    chunk = _make(lines, 0, len(lines), path=path, kind="copybook", program_id=Path(path).stem.upper())
    return [chunk] if chunk else []


# --------------------------------------------------------------------------- JCL

_EXEC = re.compile(r"^//([A-Z0-9#@$.]*)\s+EXEC\s+(.*)", re.IGNORECASE)
_PGM = re.compile(r"\bPGM=([A-Z0-9#@$&.]+)", re.IGNORECASE)


def chunk_jcl(text: str, path: str) -> list[Chunk]:
    """One chunk per EXEC step. The JOB/PROC card and comments before the first step go with it."""
    lines = text.splitlines()
    steps: list[tuple[int, str | None, str | None]] = []
    for i, line in enumerate(lines):
        if m := _EXEC.match(line):
            pgm = _PGM.search(m.group(2))
            steps.append((i, m.group(1).upper() or None, pgm.group(1).upper() if pgm else None))
    if not steps:
        chunk = _make(lines, 0, len(lines), path=path, kind="jcl")
        return [chunk] if chunk else []

    starts = []
    floor = 0
    for n, (i, step, pgm) in enumerate(steps):
        s = 0 if n == 0 else i
        while n > 0 and s > floor and lines[s - 1].startswith("//*"):
            s -= 1
        starts.append((s, step, pgm))
        floor = i + 1
    chunks = []
    for (start, end), (_, step, pgm) in zip(_spans([s for s, _, _ in starts], len(lines)), starts,
                                            strict=True):
        chunk = _make(lines, start, end, path=path, kind="jcl", program_id=pgm, paragraph=step)
        if chunk:
            chunks.append(chunk)
    return chunks


# --------------------------------------------------------------------------- Markdown

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def chunk_markdown(text: str, path: str) -> list[Chunk]:
    """One chunk per heading; text before the first heading is its own chunk."""
    lines = text.splitlines()
    starts: list[tuple[int, str | None]] = []
    in_fence = False
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and (m := _HEADING.match(line)):
            starts.append((i, m.group(2).strip()))
    if not starts or starts[0][0] > 0:
        starts.insert(0, (0, None))
    chunks = []
    for (start, end), (_, heading) in zip(_spans([s for s, _ in starts], len(lines)), starts,
                                          strict=True):
        chunk = _make(lines, start, end, path=path, kind="standard", paragraph=heading)
        if chunk:
            chunks.append(chunk)
    return chunks


CHUNKERS: dict[str, Callable[[str, str], list[Chunk]]] = {
    "program": chunk_cobol,
    "copybook": chunk_copybook,
    "jcl": chunk_jcl,
    "standard": chunk_markdown,
}
