"""RAG quality gate: hit@k over the golden queries (ADR 0001).

    python -m rag.evaluate            # exits 1 if hit@5 < 0.80
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from rag.store import REPO_ROOT

GOLDEN = REPO_ROOT / "evals" / "golden_queries.json"


@dataclass(frozen=True)
class QueryOutcome:
    id: str
    query: str
    hit: bool
    rank: int | None  # 1-based rank of the first matching result
    top: list[str]


def load_golden(path: Path = GOLDEN) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def matches(metadata: Mapping[str, object], expected: Mapping[str, object]) -> bool:
    """An expected entry matches when every key it names equals the result's metadata."""
    return all(metadata.get(key) == value for key, value in expected.items())


def evaluate(golden: dict, search: Callable[[str, int], Sequence]) -> tuple[float, list[QueryOutcome]]:
    k = golden["k"]
    outcomes = []
    for q in golden["queries"]:
        results = list(search(q["query"], k))[:k]
        rank = next((i for i, r in enumerate(results, 1)
                     if any(matches(r.metadata, e) for e in q["expect"])), None)
        outcomes.append(QueryOutcome(q["id"], q["query"], rank is not None, rank, [r.id for r in results]))
    return sum(o.hit for o in outcomes) / len(outcomes), outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rag.evaluate", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", type=Path, default=GOLDEN)
    parser.add_argument("-v", "--verbose", action="store_true", help="show top-k ids for misses")
    args = parser.parse_args(argv)

    from rag.retriever import retrieve

    golden = load_golden(args.golden)
    score, outcomes = evaluate(golden, lambda q, k: retrieve(q, k=k))
    for o in outcomes:
        mark = f"hit  @{o.rank}" if o.hit else "MISS   "
        print(f"{o.id}  {mark}  {o.query}")
        if args.verbose and not o.hit:
            for rid in o.top:
                print(f"           {rid}")
    k, threshold = golden["k"], golden["threshold"]
    passed = score >= threshold
    print(f"\nhit@{k} = {score:.2f} ({sum(o.hit for o in outcomes)}/{len(outcomes)}); "
          f"gate >= {threshold:.2f}: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
