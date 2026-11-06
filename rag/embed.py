"""Embedders: the Embedder protocol, a local Ollama implementation, and a deterministic fake for tests."""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

DEFAULT_OLLAMA_HOST = "http://localhost:11434"


@runtime_checkable
class Embedder(Protocol):
    """Turns text into vectors. ``model`` identifies the vector space and is recorded in the index."""

    model: str

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class OllamaEmbedder:
    """``nomic-embed-text`` served by a local Ollama.

    nomic-embed-text is trained with task prefixes. Documents and queries must use
    ``search_document:`` and ``search_query:`` respectively, or retrieval quality drops.
    """

    DOCUMENT_PREFIX = "search_document: "
    QUERY_PREFIX = "search_query: "

    def __init__(self, model: str = "nomic-embed-text", host: str | None = None, client=None) -> None:
        self.model = model
        if client is None:
            import ollama

            client = ollama.Client(host=host or os.environ.get("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST)
        self._client = client

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        if not inputs:
            return []
        response = self._client.embed(model=self.model, input=inputs, truncate=True)
        vectors = [list(v) for v in response["embeddings"]]
        if len(vectors) != len(inputs):
            raise RuntimeError(f"Ollama returned {len(vectors)} embeddings for {len(inputs)} inputs")
        return vectors

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed([self.DOCUMENT_PREFIX + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self.QUERY_PREFIX + text])[0]


class FakeEmbedder:
    """Deterministic hashed bag-of-words embedder for tests. No network, no model.

    Texts that share tokens get similar vectors, so vector search behaves sensibly in tests.
    """

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim
        self.model = f"fake-hash-{dim}"
        self.calls: list[list[str]] = []

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in re.findall(r"[a-z0-9#@$-]+", text.lower()):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            vec[idx] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)
