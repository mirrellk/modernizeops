"""keystone-office MCP server. Every test works on tmp_path copies of the real templates."""

import asyncio
import json
import shutil

import pytest
from docx import Document
from mcp import Client
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError
from openpyxl import load_workbook

from mcp_servers.office_server import server
from mcp_servers.office_server.server import (
    REPO_ROOT,
    DesignSections,
    ImpactRow,
    MappingRow,
    append_impact_rows,
    create_design_doc,
    mcp,
    read_impact_matrix,
)

ERROR_KEYS = {"error_category", "retryable", "message", "suggestion"}
HEADINGS = ["1 Summary", "2 Current State (Legacy)", "3 Proposed Change", "4 Data Mapping",
            "5 Impact and Risk", "6 Test Strategy", "7 Rollback", "8 Approvals"]


@pytest.fixture(autouse=True)
def office(tmp_path, monkeypatch):
    """Point the server at copies of the templates so the repo files are never written.

    Nothing is read from design/: the live register there holds real CR rows.
    """
    docx = tmp_path / "design-doc-template.docx"
    xlsx_template = tmp_path / "impact-matrix-template.xlsx"
    xlsx = tmp_path / "impact-matrix.xlsx"
    shutil.copyfile(REPO_ROOT / "templates" / "design-doc-template.docx", docx)
    shutil.copyfile(REPO_ROOT / "templates" / "impact-matrix-template.xlsx", xlsx_template)
    shutil.copyfile(xlsx_template, xlsx)
    monkeypatch.setattr(server, "DESIGN_TEMPLATE", docx)
    monkeypatch.setattr(server, "IMPACT_TEMPLATE", xlsx_template)
    monkeypatch.setattr(server, "IMPACT_MATRIX", xlsx)
    monkeypatch.setattr(server, "DESIGN_DIR", tmp_path / "design")
    return tmp_path


def error_of(excinfo) -> dict:
    body = json.loads(str(excinfo.value))
    assert set(body) == ERROR_KEYS
    assert body["message"] and body["suggestion"]
    return body


def mapping(**overrides) -> MappingRow:
    row = {"cobol_field": "ACCT-LIMIT", "copybook": "ACCT-FIELDS", "pic": "S9(7)V99 COMP-3",
               "python_name": "acct_limit", "python_type": "Decimal", "pii": "N", "notes": "ROUND_HALF_EVEN"}
    return MappingRow(**(row | overrides))


def sections(**overrides) -> DesignSections:
    body = {
        "summary": "Raise the credit limit cap.\nSecond summary paragraph.",
        "current_state": "CBL0001 reads ACCT-LIMIT (corpus/legacy/.../CBL0001.cobol:40-52).",
        "proposed_change": "Add keystone.limits.apply_cap().",
        "data_mapping": [mapping(), mapping(cobol_field="ACCT-BALANCE", python_name="acct_balance")],
        "impact_and_risk": "Medium: one program, no PII.",
        "test_strategy": "T-001 unit; T-002 parallel run.",
        "rollback": "Revert the PR and rerun the nightly job.",
        "approvals": "Needs Application Owner sign-off.",
    }
    return DesignSections(**(body | overrides))


def impact(**overrides) -> ImpactRow:
    row = {"cr_key": "MOD-1", "program": "CBL0001", "paragraph": "WRITE-RECORD", "copybook": "ACCT-FIELDS",
               "field": "ACCT-LIMIT", "change_type": "Modify", "risk": "Medium", "pii": "N", "test_id": "T-001",
               "owner": "Batch team", "status": "Open"}
    return ImpactRow(**(row | overrides))


def body_texts(path) -> list[str]:
    return [p.text for p in Document(str(path)).paragraphs if p.text.strip()]


# --------------------------------------------------------------------------- create_design_doc


def test_create_design_doc_fills_title_page_sections_and_mapping(office):
    path = create_design_doc("mod-12", "Raise limit cap", sections(), author="A. Analyst")
    out = office / "design" / "MOD-12-design.docx"
    assert path == out.as_posix() and out.is_file()

    texts = body_texts(out)
    assert not [t for t in texts if "{" in t]
    for expected in ["MOD-12: Raise limit cap", "Change Request: MOD-12", "Author: A. Analyst",
                     "Raise the credit limit cap.", "Second summary paragraph.",
                     "Add keystone.limits.apply_cap().", "Needs Application Owner sign-off."]:
        assert expected in texts
    assert texts.index("Raise the credit limit cap.") == texts.index("1 Summary") + 1
    assert texts.index("Needs Application Owner sign-off.") == texts.index("8 Approvals") + 1

    doc = Document(str(out))
    assert [p.text for p in doc.paragraphs if p.style.name == "Heading 1"] == HEADINGS
    assert "MOD-12" in doc.sections[0].header.paragraphs[0].text
    mapping_table, approvals_table = doc.tables
    rows = [[c.text for c in r.cells] for r in mapping_table.rows]
    assert rows[1] == ["ACCT-LIMIT", "ACCT-FIELDS", "S9(7)V99 COMP-3", "acct_limit", "Decimal",
                       "N", "ROUND_HALF_EVEN"]
    assert len(rows) == 3 and rows[2][0] == "ACCT-BALANCE"
    # approvals stay blank for people to sign
    assert all(not c.text for r in approvals_table.rows[1:] for c in r.cells[1:])


def test_create_design_doc_never_writes_the_template(office):
    before = (office / "design-doc-template.docx").read_bytes()
    create_design_doc("MOD-3", "x", sections())
    assert (office / "design-doc-template.docx").read_bytes() == before


@pytest.mark.parametrize("field", ["summary", "rollback", "approvals"])
def test_create_design_doc_rejects_empty_sections(field):
    with pytest.raises(ToolError) as e:
        create_design_doc("MOD-1", "t", sections(**{field: "  "}))
    body = error_of(e)
    assert body["error_category"] == "invalid_input" and body["retryable"] is False
    assert field in body["message"]


def test_create_design_doc_rejects_empty_data_mapping():
    with pytest.raises(ToolError) as e:
        create_design_doc("MOD-1", "t", sections(data_mapping=[]))
    assert "data_mapping" in error_of(e)["message"]


def test_create_design_doc_rejects_float_for_money():
    with pytest.raises(ToolError) as e:
        create_design_doc("MOD-1", "t", sections(data_mapping=[mapping(python_type="float")]))
    body = error_of(e)
    assert body["error_category"] == "invalid_input" and "Decimal" in body["message"]


@pytest.mark.parametrize("key", ["", "42", "ABC-1", "MOD-0", "MOD-1/../x"])
def test_create_design_doc_rejects_bad_cr_keys(key, office):
    with pytest.raises(ToolError) as e:
        create_design_doc(key, "t", sections())
    assert error_of(e)["error_category"] == "invalid_input"
    assert not (office / "design").exists()


def test_create_design_doc_missing_template_is_not_found(office):
    (office / "design-doc-template.docx").unlink()
    with pytest.raises(ToolError) as e:
        create_design_doc("MOD-1", "t", sections())
    assert error_of(e)["error_category"] == "not_found"


# --------------------------------------------------------------------------- impact matrix


def test_append_then_read_round_trips():
    assert append_impact_rows([impact(), impact(field="ACCT-BALANCE")]) == 2
    rows = read_impact_matrix("mod-1")
    assert [r.field for r in rows] == ["ACCT-LIMIT", "ACCT-BALANCE"]
    assert rows[0] == impact()


def test_append_upserts_on_key_and_keeps_other_rows(office):
    append_impact_rows([impact(), impact(cr_key="MOD-2", field="ACCT-ID")])
    assert append_impact_rows([impact(risk="High", status="Done"), impact(field="NEW-FIELD")]) == 2

    rows = read_impact_matrix()
    assert [(r.cr_key, r.field) for r in rows] == [
        ("MOD-1", "ACCT-LIMIT"), ("MOD-2", "ACCT-ID"), ("MOD-1", "NEW-FIELD")]
    assert (rows[0].risk, rows[0].status) == ("High", "Done")
    assert [r.field for r in read_impact_matrix("MOD-2")] == ["ACCT-ID"]


def test_append_keeps_header_freeze_filter_and_dropdowns(office):
    append_impact_rows([impact()])
    ws = load_workbook(office / "impact-matrix.xlsx")["Impact"]
    assert ws["A1"].value == "CR Key" and ws["A1"].font.bold
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref == "A1:K1000"
    assert len(ws.data_validations.dataValidation) == 4


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [({"change_type": "Delete"}, "change_type"), ({"risk": "Severe"}, "risk"),
     ({"pii": "yes"}, "pii"), ({"status": "Closed"}, "status"),
     ({"cr_key": "ABC-1"}, "cr_key"), ({"field": ""}, "field")],
)
def test_append_rejects_values_outside_the_sheet(overrides, fragment, office):
    before = (office / "impact-matrix.xlsx").read_bytes()
    with pytest.raises(ToolError) as e:
        append_impact_rows([impact(), impact(**({"field": "OTHER"} | overrides))])
    body = error_of(e)
    assert body["error_category"] == "invalid_input" and body["retryable"] is False
    assert f"rows.1.{fragment}" in body["message"]
    assert (office / "impact-matrix.xlsx").read_bytes() == before  # nothing written


def test_append_rejects_duplicate_keys_in_one_batch():
    with pytest.raises(ToolError) as e:
        append_impact_rows([impact(), impact(paragraph="write-record", risk="Low")])
    assert "duplicate key" in error_of(e)["message"]


def test_append_rejects_an_empty_batch():
    with pytest.raises(ToolError) as e:
        append_impact_rows([])
    assert error_of(e)["error_category"] == "invalid_input"


def test_allowed_values_come_from_the_sheet(office):
    """Change a dropdown in the workbook and the server follows it."""
    wb = load_workbook(office / "impact-matrix.xlsx")
    ws = wb["Impact"]
    status = next(dv for dv in ws.data_validations.dataValidation if "In Review" in dv.formula1)
    status.formula1 = '"Open,Blocked"'
    wb.save(office / "impact-matrix.xlsx")
    assert append_impact_rows([impact(status="Blocked")]) == 1
    with pytest.raises(ToolError):
        append_impact_rows([impact(status="Done")])


def test_read_impact_matrix_empty_is_not_an_error():
    assert read_impact_matrix() == []
    assert read_impact_matrix("MOD-99") == []


def test_missing_matrix_is_not_found(office):
    (office / "impact-matrix.xlsx").unlink()
    (office / "impact-matrix-template.xlsx").unlink()  # else the register is recreated from it
    with pytest.raises(ToolError) as e:
        read_impact_matrix()
    assert error_of(e)["error_category"] == "not_found"


def test_missing_matrix_is_created_from_the_template(office):
    (office / "impact-matrix.xlsx").unlink()
    template = (office / "impact-matrix-template.xlsx").read_bytes()
    assert read_impact_matrix() == []
    assert (office / "impact-matrix.xlsx").read_bytes() == template
    assert append_impact_rows([impact()]) == 1
    assert read_impact_matrix() == [impact()]
    assert (office / "impact-matrix-template.xlsx").read_bytes() == template  # never written


def test_existing_matrix_is_never_replaced_by_the_template(office):
    append_impact_rows([impact()])
    server._ensure_matrix()
    assert read_impact_matrix() == [impact()]


def test_locked_matrix_is_backend_unavailable_and_retryable(monkeypatch):
    def locked(self, filename):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("openpyxl.workbook.workbook.Workbook.save", locked)
    with pytest.raises(ToolError) as e:
        append_impact_rows([impact()])
    body = error_of(e)
    assert body["error_category"] == "backend_unavailable" and body["retryable"] is True


# --------------------------------------------------------------------------- wire


async def _wire(name: str, arguments: dict):
    async with Client(mcp) as client:
        return await client.call_tool(name, arguments)


def wire_error(name: str, arguments: dict) -> dict:
    result = asyncio.run(_wire(name, arguments))
    assert result.is_error
    body = json.loads(result.content[0].text)  # bare JSON, no "Error executing tool" prefix
    assert set(body) == ERROR_KEYS
    return body


def test_wire_missing_section_is_structured_invalid_input():
    args = sections().model_dump()
    del args["rollback"]
    body = wire_error("create_design_doc", {"cr_key": "MOD-1", "title": "t", "sections": args})
    assert body == body | {"error_category": "invalid_input", "retryable": False}
    assert "rollback" in body["message"]


def test_wire_bad_enum_is_structured_invalid_input():
    row = impact(risk="Extreme").model_dump()
    body = wire_error("append_impact_rows", {"rows": [row]})
    assert body["error_category"] == "invalid_input" and "risk" in body["message"]


def test_wire_unknown_tool_is_not_found():
    assert wire_error("delete_matrix", {})["error_category"] == "not_found"


def test_wire_round_trip_returns_structured_rows():
    asyncio.run(_wire("append_impact_rows", {"rows": [impact().model_dump()]}))
    result = asyncio.run(_wire("read_impact_matrix", {"cr_key": "MOD-1"}))
    assert not result.is_error
    assert result.structured_content["result"] == [impact().model_dump()]


# --------------------------------------------------------------------------- resources and surface


def read(uri: str) -> dict:
    return json.loads(next(iter(asyncio.run(mcp.read_resource(uri)))).content)


def test_design_doc_resource_lists_every_section_with_guidance():
    sections_ = read("templates://design-doc")["sections"]
    assert [s["heading"] for s in sections_] == HEADINGS
    assert [s["field"] for s in sections_] == list(DesignSections.model_fields)
    assert all(s["guidance"] for s in sections_)
    assert "pic-mapping" in sections_[3]["guidance"]  # taken from the template's hint text


def test_impact_columns_resource_reports_dropdowns():
    body = read("templates://impact-columns")
    columns = {c["column"]: c for c in body["columns"]}
    assert list(columns) == ["CR Key", "Program", "Paragraph", "Copybook", "Field", "Change Type",
                             "Risk", "PII", "Test ID", "Owner", "Status"]
    assert columns["Change Type"]["allowed"] == ["Add", "Modify", "Remove"]
    assert columns["Risk"]["allowed"] == ["Low", "Medium", "High"]
    assert columns["PII"]["allowed"] == ["Y", "N"]
    assert columns["Owner"]["allowed"] is None
    assert body["upsert_key"] == ["cr_key", "program", "paragraph", "field"]


def test_resource_with_missing_template_is_not_found(office):
    (office / "impact-matrix-template.xlsx").unlink()  # the resource describes the template
    with pytest.raises(ResourceNotFoundError) as e:
        read("templates://impact-columns")
    assert error_of(e)["error_category"] == "not_found"


def test_server_registers_the_spec_surface():
    async def surface():
        tools = {t.name: t for t in await mcp.list_tools()}
        resources = {str(r.uri) for r in await mcp.list_resources()}
        return tools, resources

    tools, resources = asyncio.run(surface())
    assert mcp.name == "keystone-office"
    assert set(tools) == {"create_design_doc", "append_impact_rows", "read_impact_matrix"}
    assert all("Do NOT" in t.description for t in tools.values())
    assert resources == {"templates://design-doc", "templates://impact-columns"}
