"""Retrieval evaluation over evals/retrieval_golden.jsonl: hit@5 and MRR, overall and per question.

    python -m rag.eval_retrieval                 # writes evals/reports/retrieval-<YYYY-MM-DD>.json

Each golden row is ``{"id", "question", "expected_paths": [...]}``. A question is a hit@5 when any
expected path is among the top 5 results. MRR uses the rank of the first result whose path is
expected, within the retriever's top 8 (ADR 0001), scoring 0 when none appears. Exits 1 when
hit@5 is below the ADR 0001 quality gate (0.80); the report is written either way.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from rag.store import COLLECTION, REPO_ROOT

GOLDEN = REPO_ROOT / "evals" / "retrieval_golden.jsonl"
REPORTS = REPO_ROOT / "evals" / "reports"
HIT_K = 5
RANK_DEPTH = 8
GATE = 0.80

Search = Callable[[str, int], Sequence]


def load_golden(path: Path = GOLDEN) -> list[dict]:
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not {"id", "question", "expected_paths"} <= row.keys() or not row["expected_paths"]:
            raise ValueError(f"{path}:{n}: need id, question and non-empty expected_paths")
        rows.append(row)
    return rows


def score_question(row: dict, results: Sequence) -> dict:
    expected = set(row["expected_paths"])
    ranked = [{"rank": i, "id": r.id, "path": r.metadata.get("path"), "score": round(r.score, 6),
               "expected": r.metadata.get("path") in expected}
              for i, r in enumerate(results[:RANK_DEPTH], 1)]
    first = next((r["rank"] for r in ranked if r["expected"]), None)
    found = sorted({r["path"] for r in ranked[:HIT_K] if r["expected"]})
    return {
        "id": row["id"],
        "question": row["question"],
        "expected_paths": row["expected_paths"],
        "hit_at_5": first is not None and first <= HIT_K,
        "first_relevant_rank": first,
        "reciprocal_rank": round(1 / first, 6) if first else 0.0,
        "expected_found_in_top_5": found,
        "results": ranked,
    }


def run(rows: list[dict], search: Search) -> dict:
    per_q = [score_question(row, list(search(row["question"], RANK_DEPTH))) for row in rows]
    n = len(per_q)
    hit = sum(q["hit_at_5"] for q in per_q) / n if n else 0.0
    mrr = sum(q["reciprocal_rank"] for q in per_q) / n if n else 0.0
    return {
        "overall": {
            "questions": n,
            "hit_at_5": round(hit, 4),
            "mrr": round(mrr, 4),
            "hits": sum(q["hit_at_5"] for q in per_q),
            "gate": {"metric": "hit_at_5", "threshold": GATE, "passed": hit >= GATE},
        },
        "per_question": per_q,
    }


def write_report(report: dict, out_dir: Path = REPORTS, when: datetime | None = None) -> Path:
    when = when or datetime.now(UTC).astimezone()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"retrieval-{when:%Y-%m-%d}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rag.eval_retrieval", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", type=Path, default=GOLDEN)
    parser.add_argument("--out-dir", type=Path, default=REPORTS)
    args = parser.parse_args(argv)

    from rag.retriever import _default_retriever

    retriever = _default_retriever()
    rows = load_golden(args.golden)
    report = run(rows, lambda q, k: retriever.retrieve(q, k=k))
    when = datetime.now(UTC).astimezone()
    report = {
        "generated_at": when.isoformat(timespec="seconds"),
        "golden": args.golden.resolve().relative_to(REPO_ROOT).as_posix()
        if args.golden.resolve().is_relative_to(REPO_ROOT) else str(args.golden),
        "config": {"collection": COLLECTION, "embedder": retriever.embedder.model,
                   "indexed_chunks": retriever.collection.count(),
                   "hit_k": HIT_K, "rank_depth": RANK_DEPTH},
        **report,
    }
    path = write_report(report, args.out_dir, when)

    for q in report["per_question"]:
        rank = q["first_relevant_rank"]
        mark = "hit " if q["hit_at_5"] else "MISS"
        print(f"{q['id']}  {mark}  rank={rank if rank else '-':<2}  RR={q['reciprocal_rank']:.3f}  "
              f"{q['question']}")
    o = report["overall"]
    print(f"\nhit@5 = {o['hit_at_5']:.2f} ({o['hits']}/{o['questions']})   MRR = {o['mrr']:.3f}   "
          f"gate hit@5 >= {GATE:.2f}: {'PASS' if o['gate']['passed'] else 'FAIL'}")
    print(f"report: {path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else path}")
    return 0 if o["gate"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
