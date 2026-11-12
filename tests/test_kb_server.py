"""keystone-kb MCP server. Tools are called directly; search uses FakeEmbedder over the real corpus."""

import asyncio
import json
import uuid

import chromadb.errors
import httpx
import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError

from mcp_servers.kb_server import server
from mcp_servers.kb_server.server import (
    get_source,
    impact_analysis,
    list_programs,
    mcp,
    search_kb,
)
from rag.embed import FakeEmbedder
from rag.ingest import ingest
from rag.retriever import HybridRetriever, Result
from rag.store import REPO_ROOT, ephemeral_client, open_collection

HIT_KEYS = {"path", "start_line", "end_line", "program_id", "paragraph", "score", "snippet"}
CBL0001 = "corpus/legacy/COBOL Programming Course #2 - Learning COBOL/Labs/cbl/CBL0001.cobol"


def fresh_collection():
    return open_collection(ephemeral_client(), FakeEmbedder().model, name=f"kb{uuid.uuid4().hex}")


@pytest.fixture(scope="module")
def corpus_retriever():
    collection = fresh_collection()
    ingest(collection, FakeEmbedder(), corpus=REPO_ROOT / "corpus", root=REPO_ROOT)
    return HybridRetriever(collection, FakeEmbedder())


@pytest.fixture
def kb(corpus_retriever):
    server.set_retriever(corpus_retriever)
    yield corpus_retriever
    server.set_retriever(None)


def error_of(excinfo) -> dict:
    body = json.loads(str(excinfo.value))
    assert set(body) == {"error_category", "retryable", "message", "suggestion"}
    assert body["message"] and body["suggestion"]
    return body


def hits_of(result) -> list[dict]:
    assert not result.is_error
    return result.structured_content["result"]


class _DownEmbedder(FakeEmbedder):
    """Embeds documents (for ingest) but fails on queries the way a stopped Ollama does."""

    def __init__(self, exc: Exception):
        super().__init__()
        self.exc = exc

    def embed_query(self, text):
        raise self.exc


# --------------------------------------------------------------------------- search_kb


def test_search_kb_returns_hits_with_the_documented_fields(kb):
    hits = hits_of(search_kb("ACCT-LIMIT ACCT-BALANCE COMP-3"))
    assert 1 <= len(hits) <= 8
    for h in hits:
        assert set(h) == HIT_KEYS
        assert (REPO_ROOT / h["path"]).is_file()
        assert 1 <= h["start_line"] <= h["end_line"]
        assert len(h["snippet"].splitlines()) <= 40
    assert [h["score"] for h in hits] == sorted((h["score"] for h in hits), reverse=True)
    assert any("ACCT-LIMIT" in h["snippet"] for h in hits)


def test_search_kb_snippet_is_capped_at_40_lines_for_long_chunks():
    text = "\n".join(f"LINE {i}" for i in range(1, 101))
    meta = {"path": "corpus/standards/x.md", "kind": "standard", "start_line": 11, "end_line": 110}

    class OneLongChunk:
        def retrieve(self, query, k, kind):
            return [Result("corpus/standards/x.md:11", text, meta, 0.03, 1, 1)]

    server.set_retriever(OneLongChunk())
    try:
        [hit] = hits_of(search_kb("anything"))
    finally:
        server.set_retriever(None)
    assert hit["snippet"].splitlines() == [f"LINE {i}" for i in range(1, 41)]
    assert (hit["start_line"], hit["end_line"]) == (11, 110)
    assert hit["program_id"] is None and hit["paragraph"] is None


def test_search_kb_kind_filter_and_k(kb):
    hits = hits_of(search_kb("ACCT-FIELDS record layout", kind="copybook", k=3))
    assert 1 <= len(hits) <= 3
    assert all(h["path"].startswith("corpus/legacy/copybooks/") for h in hits)
    assert all(h["paragraph"] is None and h["program_id"] for h in hits)


def test_search_kb_content_is_json_of_the_hits(kb):
    result = search_kb("PRTLINE", kind="jcl", k=2)
    assert json.loads(result.content[0].text) == hits_of(result)


def test_search_kb_empty_result_is_not_an_error_and_has_a_note():
    server.set_retriever(HybridRetriever(fresh_collection(), FakeEmbedder()))
    try:
        result = search_kb("ACCT-LIMIT", kind="jcl")
    finally:
        server.set_retriever(None)
    assert not result.is_error
    assert result.structured_content == {"result": []}
    assert result.content[0].text == "[]"
    assert "not an error" in result.content[1].text


@pytest.mark.parametrize(
    "args",
    [{"query": ""}, {"query": "   "}, {"query": "x", "kind": "cobol"}, {"query": "x", "k": 0},
     {"query": "x", "k": 21}, {"query": "x", "k": True}],
)
def test_search_kb_rejects_invalid_input(kb, args):
    with pytest.raises(ToolError) as e:
        search_kb(**args)
    body = error_of(e)
    assert body["error_category"] == "invalid_input" and body["retryable"] is False


@pytest.mark.parametrize(
    "exc",
    [ConnectionError("Failed to connect to Ollama."), httpx.ConnectError("connection refused")],
)
def test_search_kb_ollama_down_is_backend_unavailable_and_retryable(exc):
    collection = fresh_collection()
    ingest(collection, FakeEmbedder(), corpus=REPO_ROOT / "corpus" / "legacy" / "copybooks", root=REPO_ROOT)
    server.set_retriever(HybridRetriever(collection, _DownEmbedder(exc)))
    try:
        with pytest.raises(ToolError) as e:
            search_kb("ACCT-LIMIT")
    finally:
        server.set_retriever(None)
    body = error_of(e)
    assert body["error_category"] == "backend_unavailable" and body["retryable"] is True
    assert "ollama" in body["suggestion"].lower()


def test_search_kb_missing_index_is_backend_unavailable_not_retryable(monkeypatch):
    import rag.retriever

    def no_index():
        raise chromadb.errors.NotFoundError("Collection [keystone_legacy] does not exist")

    monkeypatch.setattr(rag.retriever, "_default_retriever", no_index)
    server.set_retriever(None)
    with pytest.raises(ToolError) as e:
        search_kb("ACCT-LIMIT")
    body = error_of(e)
    assert body["error_category"] == "backend_unavailable" and body["retryable"] is False
    assert "rag.ingest --rebuild" in body["suggestion"]


def test_search_kb_never_crashes_on_an_unexpected_backend_error():
    class Broken:
        def retrieve(self, query, k, kind):
            raise RuntimeError("disk on fire")

    server.set_retriever(Broken())
    try:
        result = asyncio.run(_call("search_kb", {"query": "ACCT-LIMIT"}))
    finally:
        server.set_retriever(None)
    assert result["error_category"] == "backend_unavailable"
    assert "disk on fire" in result["message"]


async def _call(name: str, arguments: dict) -> dict:
    """Call through the MCP server; a ToolError must keep its JSON body (not a generic crash)."""
    with pytest.raises(ToolError) as e:
        await mcp.call_tool(name, arguments)
    assert type(e.value) is ToolError  # not UnexpectedToolError
    return json.loads(str(e.value))


async def _wire(name: str, arguments: dict):
    """Call the tool the way a client does: in-process MCP session, results as sent on the wire."""
    async with Client(mcp) as client:
        return await client.call_tool(name, arguments)


def wire_error(name: str, arguments: dict) -> dict:
    result = asyncio.run(_wire(name, arguments))
    assert result.is_error
    body = json.loads(result.content[0].text)  # bare JSON, no "Error executing tool" prefix
    assert set(body) == {"error_category", "retryable", "message", "suggestion"}
    return body


def test_wire_tool_error_text_is_the_bare_json_body():
    body = wire_error("get_source", {"path": "pyproject.toml", "start_line": 1, "end_line": 1})
    assert body["error_category"] == "invalid_input" and "outside corpus" in body["message"]


@pytest.mark.parametrize(
    ("name", "arguments"),
    [("search_kb", {"query": "x", "kind": "cobol"}), ("search_kb", {}),
     ("get_source", {"path": "corpus/x", "start_line": "one", "end_line": 2})],
)
def test_wire_schema_violations_are_invalid_input_json(name, arguments):
    body = wire_error(name, arguments)
    assert body["error_category"] == "invalid_input" and body["retryable"] is False


def test_wire_unknown_tool_is_not_found_json():
    assert wire_error("drop_tables", {})["error_category"] == "not_found"


def test_wire_crash_is_json_without_leaking_the_exception_text(monkeypatch):
    def boom(text):
        raise KeyError("secret internal detail")

    monkeypatch.setattr(server, "parse_inventory", boom)
    body = wire_error("list_programs", {})
    assert body["error_category"] == "backend_unavailable"
    assert "secret internal detail" not in json.dumps(body)


def test_wire_search_returns_structured_hits(kb):
    result = asyncio.run(_wire("search_kb", {"query": "ACCT-LIMIT", "k": 2}))
    assert not result.is_error
    hits = result.structured_content["result"]
    assert len(hits) == 2 and set(hits[0]) == HIT_KEYS


# --------------------------------------------------------------------------- get_source


def test_get_source_returns_exact_lines():
    lines = (REPO_ROOT / CBL0001).read_text(encoding="utf-8").splitlines()
    out = get_source(CBL0001, 3, 7)
    assert out == {"path": CBL0001, "start_line": 3, "end_line": 7, "total_lines": len(lines),
                   "text": "\n".join(lines[2:7])}


def test_get_source_accepts_backslash_paths():
    assert get_source(CBL0001.replace("/", "\\"), 1, 1)["path"] == CBL0001


@pytest.mark.parametrize(
    "path",
    ["pyproject.toml", ".env", "corpus/../pyproject.toml", "corpus/legacy/../../README.md",
     str(REPO_ROOT / "pyproject.toml"), "C:/Windows/win.ini", "corpus"],
)
def test_get_source_refuses_paths_outside_corpus(path):
    with pytest.raises(ToolError) as e:
        get_source(path, 1, 1)
    body = error_of(e)
    assert body["error_category"] in {"invalid_input", "not_found"}
    if path != "corpus":
        assert body["error_category"] == "invalid_input" and "outside corpus" in body["message"]


def test_get_source_missing_file_is_not_found():
    with pytest.raises(ToolError) as e:
        get_source("corpus/legacy/NOPE.cobol", 1, 1)
    assert error_of(e)["error_category"] == "not_found"


def test_get_source_refuses_binary_data_files():
    data = next((REPO_ROOT / "corpus" / "legacy").rglob("data/data"))
    with pytest.raises(ToolError) as e:
        get_source(data.relative_to(REPO_ROOT).as_posix(), 1, 1)
    assert "binary" in error_of(e)["message"]


@pytest.mark.parametrize(("start", "end"), [(0, 1), (5, 4), (10_000, 10_001), (1, 10_000), (1, 501)])
def test_get_source_rejects_bad_ranges(start, end):
    with pytest.raises(ToolError) as e:
        get_source("corpus/standards/data-dictionary.md", start, end)
    assert error_of(e)["error_category"] == "invalid_input"


# --------------------------------------------------------------------------- list_programs


def test_list_programs_reads_every_inventory_row():
    programs = list_programs()
    assert len(programs) == 32
    for p in programs:
        assert set(p) == {"program_id", "path", "copybooks"}
        assert (REPO_ROOT / p["path"]).is_file(), p["path"]
        for c in p["copybooks"]:
            assert c["path"] is None or (REPO_ROOT / c["path"]).is_file()
    assert sum(p["program_id"] == "CBL0006" for p in programs) == 2


def test_list_programs_reports_derived_and_system_copybooks():
    by_path = {p["path"]: p for p in list_programs()}
    assert by_path[CBL0001]["copybooks"] == [
        {"name": "ACCT-FIELDS", "path": "corpus/legacy/copybooks/ACCT-FIELDS.cpy", "derived": True},
        {"name": "PRINT-REC-A", "path": "corpus/legacy/copybooks/PRINT-REC-A.cpy", "derived": True},
    ]
    db21 = next(p for p in by_path.values() if p["program_id"] == "CBLDB21")
    assert {"name": "SQLCA", "path": None, "derived": False} in db21["copybooks"]
    hello = next(p for p in by_path.values() if p["program_id"] == "HELLO")
    assert hello["copybooks"] == []


def test_list_programs_missing_inventory_is_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "INVENTORY", tmp_path / "INVENTORY.md")
    with pytest.raises(ToolError) as e:
        list_programs()
    assert error_of(e)["error_category"] == "not_found"


# --------------------------------------------------------------------------- inspect_account_file
# Synthetic ACCT-FIELDS records only; no real customer data.


def _packed(value: str, sign: str | None = None) -> bytes:
    """S9(7)V99 COMP-3 (5 bytes) for a test value, e.g. "123.45" or "-5.00"."""
    from decimal import Decimal

    d = Decimal(value)
    digits = str(abs(int(d.scaleb(2)))).rjust(9, "0")
    return bytes.fromhex(digits + (sign or ("D" if d < 0 else "C")))


def _acct_record(acct_no: str, limit: str, balance: str, *, limit_raw: bytes | None = None) -> bytes:
    text = lambda s, n: s.ljust(n).encode("cp037")
    rec = (text(acct_no, 8) + (limit_raw or _packed(limit)) + _packed(balance)
           + text("SYNTHLAST", 20) + text("SYNTHFIRST", 15) + text("1 TEST STREET", 25)
           + text("TESTCITY", 20) + text("TESTSTATE", 15) + text("", 7) + text("SYNTH COMMENT", 50))
    assert len(rec) == 170
    return rec


@pytest.fixture
def fake_corpus(tmp_path, monkeypatch):
    (tmp_path / "corpus" / "data").mkdir(parents=True)
    monkeypatch.setattr(server, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(server, "CORPUS", tmp_path / "corpus")

    def write(data: bytes, name: str = "acct") -> str:
        (tmp_path / "corpus" / "data" / name).write_bytes(data)
        return f"corpus/data/{name}"

    return write


SYNTH = [
    ("00011001", "1000.00", "999.99"),    # below
    ("00011002", "500.00", "500.00"),     # equal
    ("00011003", "200.00", "200.01"),     # above
    ("00011004", "0.00", "-12.34"),       # below (negative balance)
    ("00011005", "9999999.99", "1.00"),   # below, max limit
    ("00011006", "750.50", "750.50"),     # equal
    ("00011007", "100.00", "100.00"),     # equal
    ("00011008", "1.00", "1.00"),         # equal (4th: counted, not sampled)
]


def test_inspect_account_file_counts_totals_and_categories(fake_corpus):
    path = fake_corpus(b"".join(_acct_record(*r) for r in SYNTH))
    out = server.inspect_account_file(path)
    assert out["path"] == path
    assert (out["record_length"], out["record_count"]) == (170, 8)
    assert out["tlimit"] == "10002551.49"
    assert out["tbalance"] == "2540.16"
    assert (out["below"], out["equal"], out["above"]) == (3, 4, 1)
    by_cat = {}
    for s in out["sample_records"]:
        by_cat.setdefault(s["category"], []).append(s["record_no"])
    assert by_cat == {"below": [1, 4, 5], "equal": [2, 6, 7], "above": [3]}
    assert out["sample_records"][0] == {"record_no": 1, "acct_no_masked": "****1001",
                                        "limit": "1000.00", "balance": "999.99", "category": "below"}


def test_inspect_account_file_never_returns_names_addresses_or_full_acct_no(fake_corpus):
    out = json.dumps(server.inspect_account_file(fake_corpus(b"".join(_acct_record(*r) for r in SYNTH))))
    for secret in ("SYNTH", "TEST STREET", "TESTCITY", "TESTSTATE", "00011001"):
        assert secret not in out


def test_inspect_account_file_accepts_f_sign_nibble(fake_corpus):
    path = fake_corpus(_acct_record("00000001", "", "5.00", limit_raw=_packed("10.00", sign="F")))
    out = server.inspect_account_file(path)
    assert out["tlimit"] == "10.00" and out["below"] == 1


@pytest.mark.parametrize(
    ("raw", "what"),
    [(bytes.fromhex("000001000A"), "bad sign nibble"), (bytes.fromhex("0000A0000C"), "digit nibble A")],
)
def test_inspect_account_file_bad_packed_data_names_record_and_field(fake_corpus, raw, what):
    data = _acct_record(*SYNTH[0]) + _acct_record("00000002", "", "1.00", limit_raw=raw)
    with pytest.raises(ToolError) as e:
        server.inspect_account_file(fake_corpus(data))
    body = error_of(e)
    assert body["error_category"] == "invalid_input", what
    assert "Record 2" in body["message"] and "ACCT-LIMIT" in body["message"]


@pytest.mark.parametrize("data", [b"", b"x" * 169, _acct_record(*SYNTH[0]) + b"x"])
def test_inspect_account_file_rejects_wrong_length(fake_corpus, data):
    with pytest.raises(ToolError) as e:
        server.inspect_account_file(fake_corpus(data))
    body = error_of(e)
    assert body["error_category"] == "invalid_input" and "170" in body["message"]


@pytest.mark.parametrize("path", ["pyproject.toml", ".env", "corpus/../pyproject.toml", "C:/Windows/win.ini"])
def test_inspect_account_file_refuses_paths_outside_corpus(path):
    with pytest.raises(ToolError) as e:
        server.inspect_account_file(path)
    body = error_of(e)
    assert body["error_category"] == "invalid_input" and "outside corpus" in body["message"]


def test_inspect_account_file_missing_file_is_not_found(fake_corpus):
    with pytest.raises(ToolError) as e:
        server.inspect_account_file("corpus/data/nope")
    assert error_of(e)["error_category"] == "not_found"


def test_inspect_account_file_wire_error_is_bare_json():
    body = wire_error("inspect_account_file", {"path": "pyproject.toml"})
    assert body["error_category"] == "invalid_input"


def test_inspect_account_file_real_sample_decodes():
    sample = "corpus/legacy/COBOL Programming Course #2 - Learning COBOL/Labs/data/data"
    out = server.inspect_account_file(sample)
    assert out["record_length"] == 170 and out["record_count"] == 45
    assert out["below"] + out["equal"] + out["above"] == 45
    assert all(s["acct_no_masked"].startswith("****") for s in out["sample_records"])


# --------------------------------------------------------------------------- resources and prompt


def read(uri: str) -> str:
    return next(iter(asyncio.run(mcp.read_resource(uri)))).content


@pytest.mark.parametrize("name", ["pic-mapping", "pic-mapping.md", "PIC-MAPPING"])
def test_standards_resource_by_name(name):
    assert read(f"kb://standards/{name}") == (
        REPO_ROOT / "corpus" / "standards" / "pic-mapping.md").read_text(encoding="utf-8")


def test_copybook_resource_returns_copybook_text():
    text = read("kb://copybooks/ACCT-FIELDS")
    assert "DERIVED COPYBOOK" in text and "ACCT-LIMIT" in text


@pytest.mark.parametrize("uri", ["kb://standards/nope", "kb://copybooks/NOPE"])
def test_unknown_resource_is_not_found_with_available_names(uri):
    with pytest.raises(ResourceNotFoundError) as e:
        read(uri)
    body = json.loads(str(e.value))
    assert body["error_category"] == "not_found" and "Available:" in body["suggestion"]


def test_inventory_resource():
    assert read("kb://inventory").startswith("# Legacy Program Inventory")


def test_server_registers_the_spec_surface():
    async def surface():
        tools = {t.name: t for t in await mcp.list_tools()}
        templates = {t.uri_template for t in await mcp.list_resource_templates()}
        resources = {str(r.uri) for r in await mcp.list_resources()}
        prompts = {p.name for p in await mcp.list_prompts()}
        return tools, templates, resources, prompts

    tools, templates, resources, prompts = asyncio.run(surface())
    assert mcp.name == "keystone-kb"
    assert set(tools) == {"search_kb", "get_source", "list_programs", "inspect_account_file"}
    assert all("Do NOT" in t.description for t in tools.values())
    assert templates == {"kb://standards/{name}", "kb://copybooks/{name}"}
    assert resources == {"kb://inventory"}
    assert prompts == {"impact_analysis"}


def test_impact_analysis_prompt_fills_in_the_cr_key():
    text = impact_analysis("mod-42")
    assert "{cr_key}" not in text
    assert "runs/MOD-42/impact-analysis.md" in text and "Open questions" in text


@pytest.mark.parametrize("key", ["", "42", "ABC-1", "MOD-", "MOD-0", "MOD-1; rm -rf"])
def test_impact_analysis_rejects_non_mod_keys(key):
    with pytest.raises(ValueError):
        impact_analysis(key)
