"""Hybrid retrieval: BM25 + vector search fused with reciprocal rank fusion (RRF)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from rank_bm25 import BM25Okapi

from rag.embed import Embedder, OllamaEmbedder
from rag.store import index_text, open_collection, persistent_client

RRF_K = 60
VECTOR_TOP = 20
BM25_TOP = 20
DEFAULT_K = 8


@dataclass(frozen=True)
class Result:
    id: str
    text: str
    metadata: dict
    score: float
    bm25_rank: int | None
    vector_rank: int | None


def tokenize(text: str) -> list[str]:
    """Lowercase tokens; hyphenated COBOL names are kept whole *and* split into their parts."""
    tokens: list[str] = []
    for tok in re.findall(r"[a-z0-9#@$]+(?:-[a-z0-9#@$]+)*", text.lower()):
        tokens.append(tok)
        if "-" in tok:
            tokens.extend(p for p in tok.split("-") if p)
    return tokens


def rrf(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores


class HybridRetriever:
    def __init__(self, collection, embedder: Embedder) -> None:
        self.collection = collection
        self.embedder = embedder
        data = collection.get(include=["documents", "metadatas"])
        self._ids: list[str] = data["ids"]
        self._docs = dict(zip(data["ids"], data["documents"]))
        self._meta = dict(zip(data["ids"], data["metadatas"]))
        corpus = [tokenize(index_text(self._docs[i], self._meta[i])) for i in self._ids]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def _bm25_ranking(self, query: str, kind: str | None, n: int) -> list[str]:
        tokens = tokenize(query)
        if self._bm25 is None or not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        order = sorted(range(len(self._ids)), key=lambda i: scores[i], reverse=True)
        ranked = [self._ids[i] for i in order
                  if scores[i] > 0 and (kind is None or self._meta[self._ids[i]].get("kind") == kind)]
        return ranked[:n]

    def _vector_ranking(self, query: str, kind: str | None, n: int) -> list[str]:
        if not self._ids:
            return []
        res = self.collection.query(
            query_embeddings=[self.embedder.embed_query(query)],
            n_results=min(n, len(self._ids)),
            where={"kind": kind} if kind else None,
            include=[],
        )
        return res["ids"][0]

    def retrieve(self, query: str, k: int = DEFAULT_K, kind: str | None = None) -> list[Result]:
        """Vector top 20 + BM25 top 20, fused by RRF; returns the top ``k`` (default 8)."""
        bm25 = self._bm25_ranking(query, kind, BM25_TOP)
        vector = self._vector_ranking(query, kind, VECTOR_TOP)
        fused = rrf([bm25, vector])
        b_rank = {d: r for r, d in enumerate(bm25, 1)}
        v_rank = {d: r for r, d in enumerate(vector, 1)}
        top = sorted(fused, key=lambda d: (-fused[d], d))[:k]
        return [Result(d, self._docs[d], self._meta[d], fused[d], b_rank.get(d), v_rank.get(d)) for d in top]


@lru_cache(maxsize=1)
def _default_retriever() -> HybridRetriever:
    embedder = OllamaEmbedder()
    return HybridRetriever(open_collection(persistent_client(), embedder.model, create=False), embedder)


def retrieve(query: str, k: int = DEFAULT_K, kind: str | None = None) -> list[Result]:
    """Hybrid search over the persisted index built by ``python -m rag.ingest``."""
    return _default_retriever().retrieve(query, k=k, kind=kind)
