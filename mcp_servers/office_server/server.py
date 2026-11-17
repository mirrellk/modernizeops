"""keystone-office: MCP server that writes design documents and the impact matrix.

    uv run python -m mcp_servers.office_server.server        # stdio transport

Tools: create_design_doc, append_impact_rows and read_impact_matrix. Resources:
templates://design-doc and templates://impact-columns.

design/impact-matrix.xlsx is the live register. templates/impact-matrix-template.xlsx is its
clean template (header, frozen pane, autofilter and dropdowns, no data rows); the register is
created from it on first use only if it does not exist, and is never overwritten.

Built on the mcp 2.x ``MCPServer``, which replaced v1's ``FastMCP``, the same way as
keystone-kb (mcp_servers/kb_server/server.py).

Every anticipated tool failure raises ``ToolError`` whose message is JSON:
``{"error_category", "retryable", "message", "suggestion"}``, where error_category is one of
not_found, invalid_input or backend_unavailable.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, NoReturn, TypedDict

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError, UnexpectedToolError
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from pydantic import BaseModel, Field, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]

# Module-level so tests can point them at tmp_path copies.
DESIGN_TEMPLATE = REPO_ROOT / "templates" / "design-doc-template.docx"
IMPACT_TEMPLATE = REPO_ROOT / "templates" / "impact-matrix-template.xlsx"
IMPACT_MATRIX = REPO_ROOT / "design" / "impact-matrix.xlsx"
DESIGN_DIR = REPO_ROOT / "design"

IMPACT_SHEET = "Impact"
CR_KEY = re.compile(r"MOD-[1-9][0-9]*")
DEFAULT_AUTHOR = "ModernizeOps"

ErrorCategory = Literal["not_found", "invalid_input", "backend_unavailable"]


# --------------------------------------------------------------------------- models


class MappingRow(BaseModel):
    """One row of section 4 Data Mapping: a COBOL field and its Python counterpart."""

    cobol_field: str = Field(description="COBOL data name, e.g. ACCT-LIMIT.")
    copybook: str = Field(description="Copybook or record that holds the field, e.g. ACCT-FIELDS.")
    pic: str = Field(description="PIC clause as written, e.g. S9(7)V99 COMP-3.")
    python_name: str = Field(description="Python attribute name, e.g. acct_limit.")
    python_type: str = Field(description="Python type per pic-mapping; money is Decimal, never float.")
    pii: Literal["Y", "N"] = Field(description="Y if the field is PII per the data dictionary.")
    notes: str = Field(default="", description="Rounding, sign, EBCDIC or other conversion notes.")


class DesignSections(BaseModel):
    """Content for each heading of templates/design-doc-template.docx. All are required."""

    summary: str = Field(description="1 Summary: what is changing, why, and the business outcome.")
    current_state: str = Field(
        description="2 Current State (Legacy): affected programs, paragraphs, copybooks and JCL "
                    "as they run today, cited as path:start-end.")
    proposed_change: str = Field(
        description="3 Proposed Change: the Python modules, functions and behaviour.")
    data_mapping: list[MappingRow] = Field(
        description="4 Data Mapping: one row per affected field.")
    impact_and_risk: str = Field(
        description="5 Impact and Risk: affected programs, files, downstream consumers, PII "
                    "exposure, and an overall Low / Medium / High rating with justification.")
    test_strategy: str = Field(
        description="6 Test Strategy: unit, parallel-run and reconciliation tests, with test IDs "
                    "that match the impact matrix.")
    rollback: str = Field(description="7 Rollback: revert steps, trigger criteria, data reconciliation.")
    approvals: str = Field(
        description="8 Approvals: a note for approvers (which sign-offs this change needs and "
                    "why). The sign-off table itself is left blank for people to complete.")


# heading text in the template -> DesignSections field, in document order
SECTIONS: tuple[tuple[str, str], ...] = (
    ("1 Summary", "summary"),
    ("2 Current State (Legacy)", "current_state"),
    ("3 Proposed Change", "proposed_change"),
    ("4 Data Mapping", "data_mapping"),
    ("5 Impact and Risk", "impact_and_risk"),
    ("6 Test Strategy", "test_strategy"),
    ("7 Rollback", "rollback"),
    ("8 Approvals", "approvals"),
)


class ImpactRow(BaseModel):
    """One row of the Impact sheet in design/impact-matrix.xlsx."""

    cr_key: str = Field(description="Jira key, e.g. MOD-123.")
    program: str = Field(description="PROGRAM-ID, e.g. CBL0001.")
    paragraph: str = Field(description="PROCEDURE DIVISION paragraph, or '' if not paragraph-specific.")
    copybook: str = Field(default="", description="Copybook that holds the field, if any.")
    field: str = Field(description="COBOL data name, e.g. ACCT-LIMIT.")
    change_type: str = Field(description="One of the sheet's Change Type values (Add/Modify/Remove).")
    risk: str = Field(description="One of the sheet's Risk values (Low/Medium/High).")
    pii: str = Field(description="One of the sheet's PII values (Y/N).")
    test_id: str = Field(default="", description="Test ID that covers this row.")
    owner: str = Field(default="", description="Accountable person or team.")
    status: str = Field(description="One of the sheet's Status values.")


# sheet header -> ImpactRow field
COLUMNS: tuple[tuple[str, str], ...] = (
    ("CR Key", "cr_key"), ("Program", "program"), ("Paragraph", "paragraph"),
    ("Copybook", "copybook"), ("Field", "field"), ("Change Type", "change_type"),
    ("Risk", "risk"), ("PII", "pii"), ("Test ID", "test_id"), ("Owner", "owner"),
    ("Status", "status"),
)
UPSERT_KEY = ("cr_key", "program", "paragraph", "field")


class SectionGuide(TypedDict):
    heading: str
    field: str
    guidance: str


class ImpactColumn(TypedDict):
    column: str
    field: str
    allowed: list[str] | None


# --------------------------------------------------------------------------- server and errors


class OfficeServer(MCPServer):
    """MCPServer whose tool errors always reach the client as the bare JSON error body.

    Same contract as keystone-kb's KBServer: SDK-prefixed ToolErrors, argument-schema
    failures and crashes are all rewritten to {"error_category", "retryable", "message",
    "suggestion"}, keeping the exception type so crashes are still logged with a traceback.
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
                "suggestion": "Fix the arguments to match the tool's input schema; read "
                              "templates://design-doc or templates://impact-columns."}
    if text.startswith("Unknown tool"):
        return {"error_category": "not_found", "retryable": False, "message": text,
                "suggestion": "Use create_design_doc, append_impact_rows or read_impact_matrix."}
    kind = "an unexpected internal error" if isinstance(exc, UnexpectedToolError) else text
    return {"error_category": "backend_unavailable", "retryable": False,
            "message": f"{name} failed with {kind}.",
            "suggestion": "Retry once; if it fails again, check the keystone-office server log."}


mcp = OfficeServer(
    "keystone-office",
    instructions=(
        "Writes Keystone Federal Bank design documents (Word) and the impact matrix (Excel). "
        "Read templates://design-doc before create_design_doc and templates://impact-columns "
        "before append_impact_rows. Use read_impact_matrix to see what is already recorded."
    ),
)


def tool_error(category: ErrorCategory, message: str, suggestion: str, *, retryable: bool = False) -> ToolError:
    body = {"error_category": category, "retryable": retryable, "message": message, "suggestion": suggestion}
    return ToolError(json.dumps(body))


def _fail(category: ErrorCategory, message: str, suggestion: str, *, retryable: bool = False) -> NoReturn:
    raise tool_error(category, message, suggestion, retryable=retryable)


def _cr_key(value: str) -> str:
    key = value.strip().upper() if isinstance(value, str) else ""
    if not CR_KEY.fullmatch(key):
        _fail("invalid_input", f"cr_key must be a Jira MOD key such as MOD-123, not {value!r}.",
              "Use the key of the change request exactly as in Jira.")
    return key


def _require(path: Path, what: str) -> None:
    if not path.is_file():
        _fail("not_found", f"The {what} is missing: {_display(path)}.",
              f"Restore {_display(path)} from git.")


def _display(path: Path) -> str:
    path = path.resolve()
    return path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else path.as_posix()


def _locked(path: Path, exc: OSError) -> ToolError:
    return tool_error("backend_unavailable", f"Cannot write {_display(path)}: {exc.strerror or exc}.",
                      "Close the file if it is open in Word or Excel, then retry.", retryable=True)


# --------------------------------------------------------------------------- design doc


def _heading_paragraphs(doc: DocxDocument) -> dict[str, Paragraph]:
    return {p.text.strip(): p for p in doc.paragraphs if p.style.name == "Heading 1"}


def _next_element(paragraph: Paragraph):
    return paragraph._p.getnext()


def _is_guidance(element) -> bool:
    """The template's grey italic hint paragraph that sits under a heading."""
    if element is None or element.tag != qn("w:p"):
        return False
    p = Paragraph(element, None)
    return bool(p.runs) and all(r.italic for r in p.runs if r.text.strip())


def _set_text(paragraph: Paragraph, text: str) -> None:
    for run in paragraph.runs[1:]:
        run._r.getparent().remove(run._r)
    run = paragraph.runs[0] if paragraph.runs else paragraph.add_run()
    run.text = text
    run.italic = None
    run.font.color.rgb = None


def _fill_text_section(heading: Paragraph, text: str) -> None:
    """Replace the guidance under ``heading`` with ``text``, one paragraph per line block."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n|\n", text.strip()) if b.strip()]
    nxt = _next_element(heading)
    if _is_guidance(nxt):
        target = Paragraph(nxt, heading._parent)
    else:  # no hint paragraph in the template (8 Approvals): insert one after the heading
        new_p = OxmlElement("w:p")
        heading._p.addnext(new_p)
        target = Paragraph(new_p, heading._parent)
    _set_text(target, blocks[0])
    for block in blocks[1:]:
        clone = copy.deepcopy(target._p)
        target._p.addnext(clone)
        target = Paragraph(clone, heading._parent)
        _set_text(target, block)


def _fill_mapping_table(doc: DocxDocument, heading: Paragraph, rows: list[MappingRow]) -> None:
    nxt = _next_element(heading)
    if _is_guidance(nxt):
        nxt.getparent().remove(nxt)
    table = next(t for t in doc.tables if t._tbl is _next_element(heading))
    blank = copy.deepcopy(table.rows[-1]._tr)
    for tr in [r._tr for r in table.rows[1:]]:
        table._tbl.remove(tr)
    for row in rows:
        tr = copy.deepcopy(blank)
        table._tbl.append(tr)
        values = [row.cobol_field, row.copybook, row.pic, row.python_name, row.python_type,
                  row.pii, row.notes]
        for cell, value in zip(table.rows[-1].cells, values, strict=True):
            _set_text(cell.paragraphs[0], value)


def _replace_placeholders(doc: DocxDocument, values: dict[str, str]) -> None:
    def paragraphs():
        yield from doc.paragraphs
        for section in doc.sections:
            for part in (section.header, section.footer, section.first_page_header,
                         section.first_page_footer):
                yield from part.paragraphs

    for p in paragraphs():
        if "{" not in p.text:
            continue
        for run in p.runs:
            for key, value in values.items():
                run.text = run.text.replace(key, value)
    for key, value in values.items():
        doc.core_properties.title = (doc.core_properties.title or "").replace(key, value)


def _missing_sections(sections: DesignSections) -> list[str]:
    missing = [field for _, field in SECTIONS
               if field != "data_mapping" and not getattr(sections, field).strip()]
    if not sections.data_mapping:
        missing.append("data_mapping")
    return missing


@mcp.tool()
def create_design_doc(cr_key: str, title: str, sections: DesignSections,
                      author: str = DEFAULT_AUTHOR) -> str:
    """Write the design document for a change request from the bank's Word template.

    Use it once the impact analysis is done, to produce design/<cr_key>-design.docx. It copies
    templates/design-doc-template.docx, fills the title page (CR key, title, author, today's
    date) and every section, and fills the Data Mapping table. Calling it again for the same
    cr_key regenerates the document.

    Do NOT use it to record impact rows; use append_impact_rows. Do NOT invent approvals:
    the Approvals sign-off table is left blank for people to complete.

    Args:
        cr_key: Jira key, e.g. MOD-123.
        title: change request title.
        sections: one entry per template heading (read templates://design-doc for guidance).
            Every text section must be non-empty and data_mapping needs at least one row.
            Text may contain line breaks; each line becomes its own paragraph. python_type
            must never be float (money is Decimal).
        author: name on the title page (default "ModernizeOps").

    Returns the document's path (repo-relative when inside the repo).
    """
    key = _cr_key(cr_key)
    if not isinstance(title, str) or not title.strip():
        _fail("invalid_input", "title must be a non-empty string.", "Use the change request title from Jira.")
    missing = _missing_sections(sections)
    if missing:
        _fail("invalid_input", f"Missing or empty sections: {', '.join(missing)}.",
              "Provide content for every section; read templates://design-doc for what each needs.")
    floats = [r.cobol_field for r in sections.data_mapping if r.python_type.strip().lower() == "float"]
    if floats:
        _fail("invalid_input", f"python_type is float for {', '.join(floats)}; money and implied-"
              "decimal fields must be Decimal, never float.",
              "Map them per the pic-mapping standard (kb://standards/pic-mapping).")
    _require(DESIGN_TEMPLATE, "design-doc template")

    out = DESIGN_DIR / f"{key}-design.docx"
    try:
        DESIGN_DIR.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".docx.tmp")
        shutil.copyfile(DESIGN_TEMPLATE, tmp)
        doc = Document(str(tmp))
        headings = _heading_paragraphs(doc)
        absent = [h for h, _ in SECTIONS if h not in headings]
        if absent:
            tmp.unlink(missing_ok=True)
            _fail("backend_unavailable", f"The template has no heading(s): {', '.join(absent)}.",
                  "Restore templates/design-doc-template.docx from git.")
        _replace_placeholders(doc, {
            "{cr_key}": key, "{title}": title.strip(),
            "{author}": (author or DEFAULT_AUTHOR).strip(), "{date}": dt.date.today().isoformat(),
        })
        for heading_text, field in SECTIONS:
            heading = headings[heading_text]
            if field == "data_mapping":
                _fill_mapping_table(doc, heading, sections.data_mapping)
            else:
                _fill_text_section(heading, getattr(sections, field))
        doc.save(str(tmp))
        tmp.replace(out)
    except PermissionError as exc:
        raise _locked(out, exc) from exc
    return _display(out)


# --------------------------------------------------------------------------- impact matrix


def _ensure_matrix() -> None:
    """Create the live register from the clean template if, and only if, it does not exist."""
    if IMPACT_MATRIX.is_file():
        return
    _require(IMPACT_TEMPLATE, "impact-matrix template")
    try:
        IMPACT_MATRIX.parent.mkdir(parents=True, exist_ok=True)
        # "xb" fails rather than overwrite a register created meanwhile
        with IMPACT_TEMPLATE.open("rb") as src, IMPACT_MATRIX.open("xb") as dst:
            shutil.copyfileobj(src, dst)
    except FileExistsError:
        pass
    except PermissionError as exc:
        raise _locked(IMPACT_MATRIX, exc) from exc


def _load_sheet(path: Path):
    """Open ``path`` and check its Impact sheet has the expected headers."""
    wb = load_workbook(path)
    if IMPACT_SHEET not in wb.sheetnames:
        _fail("backend_unavailable", f"{_display(path)} has no {IMPACT_SHEET!r} sheet.",
              f"Restore {_display(path)} from git.")
    ws = wb[IMPACT_SHEET]
    headers = [c.value for c in ws[1]][:len(COLUMNS)]
    expected = [h for h, _ in COLUMNS]
    if headers != expected:
        _fail("backend_unavailable", f"The {IMPACT_SHEET} sheet's headers are {headers}, expected {expected}.",
              f"Restore {_display(path)} from git.")
    return wb, ws


def _open_matrix():
    _ensure_matrix()
    return _load_sheet(IMPACT_MATRIX)


def _allowed_values(ws: Worksheet) -> dict[str, list[str]]:
    """Header -> dropdown values, read from the sheet's list data validations."""
    letters = {ws.cell(row=1, column=i).column_letter: h for i, (h, _) in enumerate(COLUMNS, start=1)}
    allowed: dict[str, list[str]] = {}
    for dv in ws.data_validations.dataValidation:
        if dv.type != "list" or not dv.formula1 or not dv.formula1.startswith('"'):
            continue
        values = [v.strip() for v in dv.formula1.strip('"').split(",")]
        for rng in dv.sqref.ranges:
            header = letters.get(re.sub(r"\d", "", str(rng).split(":")[0]))
            if header:
                allowed[header] = values
    return allowed


def _data_rows(ws: Worksheet):
    """(row number, values) for every non-empty data row."""
    for r in range(2, ws.max_row + 1):
        values = ["" if ws.cell(row=r, column=c).value is None else str(ws.cell(row=r, column=c).value)
                  for c in range(1, len(COLUMNS) + 1)]
        if any(v.strip() for v in values):
            yield r, values


def _row_key(values: dict[str, str]) -> tuple[str, ...]:
    return tuple(values[f].strip().upper() for f in UPSERT_KEY)


@mcp.tool()
def append_impact_rows(rows: list[ImpactRow]) -> int:
    """Add or update rows in the Impact sheet of design/impact-matrix.xlsx.

    If the register does not exist yet it is first created from
    templates/impact-matrix-template.xlsx. Use it after the impact analysis, one row per (program, paragraph, field) a change
    touches. Rows are upserted on (CR Key, Program, Paragraph, Field): a row with a new key
    is appended after the last data row; a row whose key already exists updates that row in
    place. Other rows, the header, filters and dropdowns are never touched. The whole batch
    is validated first and nothing is written if any row is invalid.

    Do NOT use it to read the matrix; use read_impact_matrix. Do NOT use it for design-doc
    content; use create_design_doc.

    Args:
        rows: 1 or more rows. change_type, risk, pii and status must be one of the values in
            the sheet's dropdowns (read templates://impact-columns). cr_key must be a MOD key.
            A batch may not contain the same key twice.

    Returns the number of rows written (appended plus updated).
    """
    if not rows:
        _fail("invalid_input", "rows must contain at least one row.", "Pass one row per affected field.")
    wb, ws = _open_matrix()
    allowed = _allowed_values(ws)

    problems: list[str] = []
    records: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()
    for i, row in enumerate(rows):
        values = {f: getattr(row, f).strip() for _, f in COLUMNS}
        if not CR_KEY.fullmatch(values["cr_key"].upper()):
            problems.append(f"rows.{i}.cr_key: {values['cr_key']!r} is not a MOD key such as MOD-123")
        values["cr_key"] = values["cr_key"].upper()
        for field in ("program", "field"):
            if not values[field]:
                problems.append(f"rows.{i}.{field}: must not be empty")
        for header, field in COLUMNS:
            options = allowed.get(header)
            if options is not None and values[field] not in options:
                problems.append(f"rows.{i}.{field}: {values[field]!r} is not one of {options}")
        key = _row_key(values)
        if key in seen:
            problems.append(f"rows.{i}: duplicate key {key} in this batch")
        seen.add(key)
        records.append(values)
    if problems:
        _fail("invalid_input", "Invalid impact rows: " + "; ".join(problems) + ".",
              "Fix the rows and resend the whole batch; read templates://impact-columns.")

    existing: dict[tuple[str, ...], int] = {}
    last = 1
    for r, cells in _data_rows(ws):
        existing.setdefault(_row_key(dict(zip([f for _, f in COLUMNS], cells, strict=True))), r)
        last = r
    for values in records:
        target = existing.get(_row_key(values))
        if target is None:
            last += 1
            target = last
        for c, (_, field) in enumerate(COLUMNS, start=1):
            ws.cell(row=target, column=c).value = values[field]
    try:
        wb.save(IMPACT_MATRIX)
    except PermissionError as exc:
        raise _locked(IMPACT_MATRIX, exc) from exc
    return len(records)


@mcp.tool()
def read_impact_matrix(cr_key: str | None = None) -> list[ImpactRow]:
    """Read rows from the Impact sheet of design/impact-matrix.xlsx.

    Use it to see what is already recorded for a change request before adding rows, or to
    build the Impact and Risk section of a design doc.

    Do NOT use it to change the matrix; use append_impact_rows.

    Args:
        cr_key: a MOD key to return only that change request's rows; omit for every row.

    Returns a list of rows in sheet order, each with the fields of append_impact_rows
    (cr_key, program, paragraph, copybook, field, change_type, risk, pii, test_id, owner,
    status). An empty list is not an error; a register that does not exist yet is created
    empty from templates/impact-matrix-template.xlsx.
    """
    key = _cr_key(cr_key) if cr_key is not None else None
    _, ws = _open_matrix()
    fields = [f for _, f in COLUMNS]
    out: list[ImpactRow] = []
    for _, cells in _data_rows(ws):
        row = ImpactRow(**dict(zip(fields, cells, strict=True)))
        if key is None or row.cr_key.strip().upper() == key:
            out.append(row)
    return out


# --------------------------------------------------------------------------- resources


@contextmanager
def _as_resource_error():
    """Report a missing or broken template as ResourceNotFoundError, keeping the JSON body."""
    try:
        yield
    except ToolError as exc:
        raise ResourceNotFoundError(str(exc)) from exc


def design_sections() -> list[SectionGuide]:
    """Each template heading with its DesignSections field and guidance.

    Guidance is the template's own hint paragraph under the heading, so it stays in sync
    with the .docx; headings without one fall back to the field's description.
    """
    _require(DESIGN_TEMPLATE, "design-doc template")
    headings = _heading_paragraphs(Document(str(DESIGN_TEMPLATE)))
    fields = DesignSections.model_fields
    guide: list[SectionGuide] = []
    for heading_text, field in SECTIONS:
        heading = headings.get(heading_text)
        nxt = _next_element(heading) if heading is not None else None
        hint = Paragraph(nxt, None).text.strip() if _is_guidance(nxt) else ""
        guide.append(SectionGuide(heading=heading_text, field=field,
                                  guidance=hint or fields[field].description or ""))
    return guide


@mcp.resource("templates://design-doc", mime_type="application/json",
              description="Design-doc sections in order: heading, DesignSections field, guidance.")
def design_doc_template() -> str:
    with _as_resource_error():
        body = {"template": _display(DESIGN_TEMPLATE), "sections": design_sections(),
                "data_mapping_columns": list(MappingRow.model_fields)}
    return json.dumps(body, indent=1)


@mcp.resource("templates://impact-columns", mime_type="application/json",
              description="Impact sheet columns from templates/impact-matrix-template.xlsx: header, "
                          "ImpactRow field, allowed dropdown values. Rows go to design/impact-matrix.xlsx.")
def impact_columns() -> str:
    with _as_resource_error():
        _require(IMPACT_TEMPLATE, "impact-matrix template")
        _, ws = _load_sheet(IMPACT_TEMPLATE)
    allowed = _allowed_values(ws)
    columns = [ImpactColumn(column=h, field=f, allowed=allowed.get(h)) for h, f in COLUMNS]
    return json.dumps({"template": _display(IMPACT_TEMPLATE), "workbook": _display(IMPACT_MATRIX),
                       "sheet": IMPACT_SHEET, "upsert_key": list(UPSERT_KEY), "columns": columns},
                      indent=1)


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
