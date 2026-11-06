import json
from datetime import datetime

from rag.eval_retrieval import GOLDEN, load_golden, run, score_question, write_report
from rag.store import REPO_ROOT


class R:
    def __init__(self, path: str, score: float = 0.5):
        self.id, self.metadata, self.score = f"{path}:1", {"path": path}, score


def test_golden_file_has_15_unique_questions_with_real_legacy_paths():
    rows = load_golden(GOLDEN)
    assert len(rows) == 15
    assert len({r["id"] for r in rows}) == 15
    for r in rows:
        assert r["question"].strip().endswith("?")
        for p in r["expected_paths"]:
            assert p.startswith("corpus/legacy/"), p
            assert (REPO_ROOT / p).is_file(), p


def test_score_question_hit_and_reciprocal_rank():
    row = {"id": "x", "question": "q?", "expected_paths": ["b", "c"]}
    q = score_question(row, [R("a"), R("a"), R("c"), R("b")])
    assert q["hit_at_5"] is True
    assert q["first_relevant_rank"] == 3
    assert q["reciprocal_rank"] == round(1 / 3, 6)
    assert q["expected_found_in_top_5"] == ["b", "c"]
    assert [r["expected"] for r in q["results"]] == [False, False, True, True]


def test_relevant_result_at_rank_6_to_8_counts_for_mrr_but_not_hit_at_5():
    row = {"id": "x", "question": "q?", "expected_paths": ["z"]}
    q = score_question(row, [R(f"n{i}") for i in range(5)] + [R("z")] + [R("n9")] * 5)
    assert q["hit_at_5"] is False
    assert q["first_relevant_rank"] == 6 and q["reciprocal_rank"] == round(1 / 6, 6)
    assert len(q["results"]) == 8


def test_miss_scores_zero():
    q = score_question({"id": "x", "question": "q?", "expected_paths": ["z"]}, [R("a")] * 8)
    assert (q["hit_at_5"], q["first_relevant_rank"], q["reciprocal_rank"]) == (False, None, 0.0)


def test_run_aggregates_hit_at_5_mrr_and_gate():
    rows = [
        {"id": "1", "question": "a?", "expected_paths": ["p1"]},
        {"id": "2", "question": "b?", "expected_paths": ["p2"]},
    ]
    answers = {"a?": [R("p1")], "b?": [R("x"), R("p2")]}
    report = run(rows, lambda q, k: answers[q])
    assert report["overall"]["hit_at_5"] == 1.0
    assert report["overall"]["mrr"] == 0.75
    assert report["overall"]["gate"]["passed"] is True
    assert [q["id"] for q in report["per_question"]] == ["1", "2"]


def test_write_report_uses_dated_filename(tmp_path):
    path = write_report({"overall": {}}, tmp_path, datetime(2026, 11, 6, 9, 30))
    assert path.name == "retrieval-2026-11-06.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"overall": {}}
