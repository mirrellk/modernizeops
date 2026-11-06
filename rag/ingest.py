"""Index corpus/ into Chroma.

    python -m rag.ingest            # upsert changed chunks, delete chunks that no longer exist
    python -m rag.ingest --rebuild  # drop the collection and re-index everything
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from rag.chunkers import KINDS, Chunk, chunk_text, kind_for
from rag.embed import Embedder, OllamaEmbedder
from rag.store import REPO_ROOT, index_text, open_collection, persistent_client

BATCH_SIZE = 32
DEFAULT_CORPUS = REPO_ROOT / "corpus"


@dataclass
class IngestReport:
    files: Counter = field(default_factory=Counter)
    chunks: Counter = field(default_factory=Counter)
    skipped: list[str] = field(default_factory=list)
    binary: list[str] = field(default_factory=list)
    deleted: int = 0


_TEXT_CONTROLS = {9, 10, 12, 13}


def is_binary(data: bytes) -> bool:
    """True for data files (e.g. EBCDIC/packed datasets): NUL bytes or >5% control bytes."""
    sample = data[:8192]
    if b"\x00" in sample:
        return True
    controls = sum(1 for b in sample if b < 32 and b not in _TEXT_CONTROLS)
    return bool(sample) and controls / len(sample) > 0.05


def iter_chunks(corpus: Path, root: Path, report: IngestReport) -> Iterator[Chunk]:
    for path in sorted(p for p in corpus.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        data = path.read_bytes()
        if is_binary(data):
            report.binary.append(rel)
            continue
        kind = kind_for(path)
        if kind is None:
            report.skipped.append(rel)
            continue
        text = data.decode("utf-8", errors="replace")
        chunks = chunk_text(text, rel, kind)
        report.files[kind] += 1
        report.chunks[kind] += len(chunks)
        yield from chunks


def _batches(items: list[Chunk], size: int) -> Iterable[list[Chunk]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def ingest(collection, embedder: Embedder, corpus: Path = DEFAULT_CORPUS, root: Path = REPO_ROOT,
           batch_size: int = BATCH_SIZE) -> IngestReport:
    report = IngestReport()
    chunks = list(iter_chunks(corpus, root, report))
    ids = [c.id for c in chunks]
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    if dupes:
        raise ValueError(f"duplicate chunk ids: {dupes[:5]}")

    for batch in _batches(chunks, batch_size):
        vectors = embedder.embed_documents([index_text(c.text, c.metadata) for c in batch])
        collection.upsert(
            ids=[c.id for c in batch],
            documents=[c.text for c in batch],
            metadatas=[dict(c.metadata) for c in batch],
            embeddings=vectors,
        )

    stale = sorted(set(collection.get(include=[])["ids"]) - set(ids))
    if stale:
        collection.delete(ids=stale)
    report.deleted = len(stale)
    return report


def format_report(report: IngestReport) -> str:
    kinds = [k for k in KINDS if k in report.files or k in report.chunks]
    width = max([len(k) for k in kinds] + [5])
    lines = [f"{'kind':<{width}}  {'files':>5}  {'chunks':>6}"]
    lines += [f"{k:<{width}}  {report.files[k]:>5}  {report.chunks[k]:>6}" for k in kinds]
    lines.append(f"{'total':<{width}}  {sum(report.files.values()):>5}  {sum(report.chunks.values()):>6}")
    if report.binary:
        lines.append(f"skipped {len(report.binary)} binary file(s): {', '.join(report.binary)}")
    if report.skipped:
        lines.append(f"skipped {len(report.skipped)} file(s) with no chunker: {', '.join(report.skipped)}")
    if report.deleted:
        lines.append(f"deleted {report.deleted} stale chunk(s)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rag.ingest", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild", action="store_true", help="drop and recreate the collection first")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    args = parser.parse_args(argv)

    embedder = OllamaEmbedder()
    collection = open_collection(persistent_client(), embedder.model, rebuild=args.rebuild)
    report = ingest(collection, embedder, corpus=args.corpus.resolve())
    print(format_report(report))
    print(f"collection now holds {collection.count()} chunk(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
