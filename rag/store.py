"""Chroma collection access and the text representation shared by ingest and retrieval."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import chromadb
from chromadb.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PERSIST_DIR = REPO_ROOT / ".rag" / "chroma"
COLLECTION = "keystone_legacy"
EMBEDDER_KEY = "embedder"

_HEADER_KEYS = ("program_id", "division", "paragraph")


class EmbedderMismatchError(RuntimeError):
    """The collection was built with a different embedding model than the one supplied."""


def persistent_client(path: str | Path = DEFAULT_PERSIST_DIR) -> chromadb.ClientAPI:
    Path(path).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))


def ephemeral_client() -> chromadb.ClientAPI:
    return chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False, allow_reset=True))


def open_collection(client: chromadb.ClientAPI, model: str, *, rebuild: bool = False, name: str = COLLECTION,
                    create: bool = True):
    """Open (or create) the collection, enforcing that it was built with ``model``."""
    if rebuild and name in {getattr(c, "name", c) for c in client.list_collections()}:
        client.delete_collection(name)
    if create:
        collection = client.get_or_create_collection(
            name,
            configuration={"hnsw": {"space": "cosine"}},
            metadata={EMBEDDER_KEY: model},
            embedding_function=None,
        )
    else:
        collection = client.get_collection(name, embedding_function=None)
    built_with = (collection.metadata or {}).get(EMBEDDER_KEY)
    if built_with != model:
        raise EmbedderMismatchError(
            f"collection {name!r} was built with embedder {built_with!r}, not {model!r}; "
            "re-run `python -m rag.ingest --rebuild`"
        )
    return collection


def context_header(metadata: Mapping[str, object]) -> str:
    """One line locating a chunk in the corpus; prepended to the text for embedding and BM25."""
    parts = [f"{metadata.get('path')} [{metadata.get('kind')}]"]
    seen: set[str] = set()
    for key in _HEADER_KEYS:
        value = metadata.get(key)
        if value in (None, "") or str(value) in seen:
            continue
        seen.add(str(value))
        parts.append(f"{key}={value}")
    return " | ".join(parts)


def index_text(text: str, metadata: Mapping[str, object]) -> str:
    return f"{context_header(metadata)}\n{text}"
