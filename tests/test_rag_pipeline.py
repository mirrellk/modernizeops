import uuid
from pathlib import Path

import pytest

from rag.chunkers import chunk_text
from rag.embed import Embedder, FakeEmbedder, OllamaEmbedder
from rag.evaluate import evaluate, load_golden, matches
from rag.ingest import ingest, is_binary
from rag.retriever import BM25_TOP, VECTOR_TOP, HybridRetriever, rrf, tokenize
from rag.store import (
    COLLECTION,
    REPO_ROOT,
    EmbedderMismatchError,
    ephemeral_client,
    open_collection,
)

COBOL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID.    TOTALS.
       DATA DIVISION.
       FILE SECTION.
       FD  ACCT-REC RECORDING MODE F.
       01  ACCT-FIELDS.
           05  ACCT-LIMIT         PIC S9(7)V99 COMP-3.
           05  ACCT-BALANCE       PIC S9(7)V99 COMP-3.
       PROCEDURE DIVISION.
       ADD-TOTALS.
           COMPUTE TLIMIT = TLIMIT + ACCT-LIMIT END-COMPUTE.
"""
JCL = """\
//TOTALSJ JOB 1
//RUN     EXEC PGM=TOTALS
//ACCTREC   DD DSN=&SYSUID..DATA,DISP=SHR
"""
COPYBOOK = """       01  ACCT-FIELDS.
           05  ACCT-NO            PIC X(8).
"""
MD = "# Rounding\n\nUse ROUND_HALF_UP only where the COBOL statement says ROUNDED.\n"


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    (root / "legacy").mkdir(parents=True)
    (root / "standards").mkdir()
    (root / "legacy" / "TOTALS.cbl").write_text(COBOL)
    (root / "legacy" / "TOTALSJ.jcl").write_text(JCL)
    (root / "legacy" / "LICENSE").write_text("license text")
    (root / "legacy" / "copybooks").mkdir()
    (root / "legacy" / "copybooks" / "ACCTREC.cpy").write_text(COPYBOOK)
    (root / "legacy" / "data").write_bytes(bytes([0xF1, 0xF8, 0x00, 0x00, 0x12, 0x34, 0x5C]) * 40)
    (root / "standards" / "rounding.md").write_text(MD)
    return root


@pytest.fixture
def collection():
    return open_collection(ephemeral_client(), FakeEmbedder().model, name=f"t{uuid.uuid4().hex}")


def test_fake_embedder_is_deterministic_and_satisfies_protocol():
    a, b = FakeEmbedder(), FakeEmbedder()
    assert isinstance(a, Embedder)
    assert a.embed_query("ACCT-LIMIT total") == b.embed_query("ACCT-LIMIT total")
    assert a.embed_documents(["x", "y"]) == b.embed_documents(["x", "y"])


def test_ollama_embedder_applies_nomic_prefixes_without_network():
    class FakeClient:
        def __init__(self):
            self.inputs = []

        def embed(self, model, input, truncate):
            self.inputs.append((model, list(input)))
            return {"embeddings": [[0.0, 1.0] for _ in input]}

    client = FakeClient()
    emb = OllamaEmbedder(client=client)
    emb.embed_documents(["chunk one", "chunk two"])
    emb.embed_query("where is ACCT-LIMIT totaled?")
    assert client.inputs == [
        ("nomic-embed-text", ["search_document: chunk one", "search_document: chunk two"]),
        ("nomic-embed-text", ["search_query: where is ACCT-LIMIT totaled?"]),
    ]


def test_ingest_counts_kinds_and_skips_binary_and_unknown_files(corpus, collection):
    report = ingest(collection, FakeEmbedder(), corpus=corpus, root=corpus.parent)
    assert dict(report.files) == {"program": 1, "copybook": 1, "jcl": 1, "standard": 1}
    assert report.binary == ["corpus/legacy/data"]
    assert report.skipped == ["corpus/legacy/LICENSE"]
    assert collection.count() == sum(report.chunks.values())


def test_ingest_uses_stable_path_line_ids_and_is_idempotent(corpus, collection):
    ingest(collection, FakeEmbedder(), corpus=corpus, root=corpus.parent)
    first = sorted(collection.get(include=[])["ids"])
    assert "corpus/legacy/TOTALS.cbl:1" in first
    assert "corpus/legacy/TOTALSJ.jcl:1" in first
    ingest(collection, FakeEmbedder(), corpus=corpus, root=corpus.parent)
    assert sorted(collection.get(include=[])["ids"]) == first


def test_ingest_embeds_in_batches_of_32(corpus, collection):
    many = "".join(f"# Section {i}\n\nbody text number {i} " + "word " * 80 + "\n\n" for i in range(70))
    (corpus / "standards" / "many.md").write_text(many)
    emb = FakeEmbedder()
    report = ingest(collection, emb, corpus=corpus, root=corpus.parent)
    sizes = [len(c) for c in emb.calls]
    assert sum(sizes) == sum(report.chunks.values())
    assert all(s == 32 for s in sizes[:-1]) and 0 < sizes[-1] <= 32


def test_ingest_deletes_chunks_for_removed_files(corpus, collection):
    ingest(collection, FakeEmbedder(), corpus=corpus, root=corpus.parent)
    (corpus / "legacy" / "TOTALSJ.jcl").unlink()
    report = ingest(collection, FakeEmbedder(), corpus=corpus, root=corpus.parent)
    assert report.deleted >= 1
    assert not any(i.startswith("corpus/legacy/TOTALSJ.jcl") for i in collection.get(include=[])["ids"])


def test_open_collection_rejects_a_different_embedder():
    client, name = ephemeral_client(), f"t{uuid.uuid4().hex}"
    open_collection(client, FakeEmbedder().model, name=name)
    with pytest.raises(EmbedderMismatchError):
        open_collection(client, "nomic-embed-text", name=name)


def test_tokenize_keeps_hyphenated_names_and_their_parts():
    assert tokenize("MOVE ACCT-LIMIT TO ACCT-LIMIT-O.") == [
        "move", "acct-limit", "acct", "limit", "to", "acct-limit-o", "acct", "limit", "o",
    ]


def test_rrf_rewards_agreement_between_rankings():
    scores = rrf([["a", "b", "c"], ["b", "a", "d"]])
    assert scores["a"] == scores["b"] > scores["c"] > 0
    assert scores["c"] == scores["d"]


def test_retrieve_finds_exact_cobol_identifier_and_reports_ranks(corpus, collection):
    ingest(collection, FakeEmbedder(), corpus=corpus, root=corpus.parent)
    results = HybridRetriever(collection, FakeEmbedder()).retrieve("TLIMIT ACCT-LIMIT COMPUTE", k=3)
    top = results[0]
    assert top.metadata["path"] == "corpus/legacy/TOTALS.cbl"
    assert "COMPUTE TLIMIT" in top.text
    assert top.bm25_rank == 1 and top.vector_rank is not None
    assert [r.score for r in results] == sorted((r.score for r in results), reverse=True)


def test_retrieve_kind_filter_applies_to_both_searches(corpus, collection):
    ingest(collection, FakeEmbedder(), corpus=corpus, root=corpus.parent)
    results = HybridRetriever(collection, FakeEmbedder()).retrieve("ACCTREC TOTALS", k=8, kind="jcl")
    assert results and {r.metadata["kind"] for r in results} == {"jcl"}


def test_is_binary_detects_packed_data_but_not_source():
    assert is_binary(bytes([0xF1, 0x00, 0x12, 0x3C]))
    assert is_binary(bytes(range(1, 9)) * 20)
    assert not is_binary(COBOL.encode())
    assert not is_binary("café — résumé".encode())
    assert not is_binary(b"")


def test_store_uses_table_collection_name():
    assert COLLECTION == "keystone_legacy"


def test_retrieve_fuses_at_most_top_20_from_each_search(corpus, collection, monkeypatch):
    many = "".join(f"# Note {i}\n\nACCT-LIMIT note number {i}\n\n" for i in range(60))
    (corpus / "standards" / "many.md").write_text(many)
    ingest(collection, FakeEmbedder(), corpus=corpus, root=corpus.parent)
    retriever = HybridRetriever(collection, FakeEmbedder())
    seen = {}
    for name in ("_bm25_ranking", "_vector_ranking"):
        original = getattr(retriever, name)

        def spy(query, kind, n, _name=name, _original=original):
            out = _original(query, kind, n)
            seen[_name] = (n, len(out))
            return out

        monkeypatch.setattr(retriever, name, spy)
    results = retriever.retrieve("ACCT-LIMIT note")
    assert (VECTOR_TOP, BM25_TOP) == (20, 20)
    assert seen == {"_bm25_ranking": (20, 20), "_vector_ranking": (20, 20)}
    assert len(results) == 8


def test_golden_queries_meet_table_spec_and_point_at_real_chunks():
    golden = load_golden()
    assert golden["k"] == 5 and golden["threshold"] == 0.8
    queries = golden["queries"]
    assert len(queries) == 15
    assert len({q["id"] for q in queries}) == 15
    for q in queries:
        assert q["query"].strip() and q["expect"]
        for exp in q["expect"]:
            path = REPO_ROOT / exp["path"]
            assert path.is_file(), exp["path"]
            chunks = chunk_text(path.read_text(encoding="utf-8", errors="replace"), exp["path"])
            assert any(matches(c.metadata, exp) for c in chunks), (q["id"], exp)


def test_evaluate_computes_hit_at_k_and_first_matching_rank():
    class R:
        def __init__(self, path):
            self.id, self.metadata = f"{path}:1", {"path": path}

    golden = {"k": 2, "threshold": 0.5, "queries": [
        {"id": "a", "query": "x", "expect": [{"path": "p1"}]},
        {"id": "b", "query": "y", "expect": [{"path": "p9"}]},
    ]}
    score, outcomes = evaluate(golden, lambda q, k: [R("p0"), R("p1"), R("p9")])
    assert score == 0.5
    assert [(o.hit, o.rank) for o in outcomes] == [(True, 2), (False, None)]
