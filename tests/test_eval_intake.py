"""Tests for scripts/eval_intake.py: golden-set loading and scoring (no claude calls)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "eval_intake.py"

_spec = importlib.util.spec_from_file_location("eval_intake", SCRIPT)
ei = importlib.util.module_from_spec(_spec)
sys.modules["eval_intake"] = ei  # dataclasses resolve annotations through sys.modules
_spec.loader.exec_module(ei)


def _expected(**overrides) -> ei.Expected:
    base = {"cr_key": "MOD-1", "ready": True, "risk": "high", "pii": True,
            "programs": ["CBL0008"], "min_missing_questions": 0}
    base.update(overrides)
    return ei.Expected(**base)


def _result() -> ei.CaseResult:
    return ei.CaseResult("case", "MOD-1", "runs/eval/x/case-brief.json")


def test_golden_set_loads_eight_cases():
    cases = ei.load_cases(ei.GOLDEN_DIR)
    assert len(cases) == 8
    assert len({c.expected.cr_key for c in cases}) == 8


def test_golden_expectations_are_consistent_with_schema_rules():
    for case in ei.load_cases(ei.GOLDEN_DIR):
        e = case.expected
        if e.ready:
            assert e.programs and e.min_missing_questions == 0, case.name
        else:
            assert e.min_missing_questions >= 1, case.name


def test_load_expected_rejects_bad_fields(tmp_path):
    path = tmp_path / "x.expected.json"
    path.write_text(json.dumps({"cr_key": "X-1", "ready": "yes", "risk": "huge", "pii": True,
                                "programs": [], "min_missing_questions": -1}))
    with pytest.raises(ValueError, match="cr_key.*ready.*risk.*min_missing"):
        ei.load_expected(path)


def test_load_cases_requires_expected_file(tmp_path):
    (tmp_path / "lonely.md").write_text("# MOD-1: x\n")
    with pytest.raises(ValueError, match="no lonely.expected.json"):
        ei.load_cases(tmp_path)


def test_load_cases_rejects_unknown_only(tmp_path):
    with pytest.raises(ValueError, match="unknown case"):
        ei.load_cases(ei.GOLDEN_DIR, ["no-such-case"])


@pytest.mark.parametrize(("a", "b", "expected"), [
    ([], [], 1.0),
    (["A"], [], 0.0),
    (["A", "B"], ["B", "C"], 1 / 3),
    (["A", "A"], ["A"], 1.0),
])
def test_jaccard(a, b, expected):
    assert ei.jaccard(a, b) == pytest.approx(expected)


def test_score_case_perfect_match():
    r = _result()
    brief = {"ready": True, "risk": "high", "pii": True, "programs": ["CBL0008"],
             "missing_information": [], "analysis_notes": ["n"]}
    ei.score_case(r, brief, _expected())
    assert (r.ready_ok, r.risk_ok, r.pii_ok, r.missing_ok) == (True, True, True, True)
    assert r.programs_jaccard == 1.0
    assert r.actual["analysis_notes_count"] == 1


def test_score_case_mismatches_and_non_boolean_ready():
    r = _result()
    brief = {"ready": 1, "risk": "medium", "pii": "true", "programs": ["CBL0001"],
             "missing_information": [{"question": "q", "why_it_blocks": "w"}]}
    ei.score_case(r, brief, _expected(min_missing_questions=2))
    assert not (r.ready_ok or r.risk_ok or r.pii_ok or r.missing_ok)
    assert r.programs_jaccard == 0.0
    assert r.missing_count == 1


def test_score_case_missing_brief_scores_zero():
    r = _result()
    ei.score_case(r, None, _expected(programs=[]))
    assert not (r.ready_ok or r.risk_ok or r.pii_ok or r.missing_ok)
    assert r.programs_jaccard == 0.0
    assert r.expected["programs"] == []


def test_summarize_and_gates():
    good, bad = _result(), _result()
    good.ready_ok = good.schema_valid = good.risk_ok = good.pii_ok = good.missing_ok = True
    good.programs_jaccard = 1.0
    bad.schema_valid = True
    metrics = ei.summarize([good, bad])
    assert metrics["ready_accuracy"] == 0.5
    assert metrics["schema_valid_rate"] == 1.0
    assert metrics["programs_jaccard_mean"] == 0.5
    failures = ei.gate_failures(metrics)
    assert len(failures) == 1 and failures[0].startswith("ready_accuracy")
    assert ei.gate_failures(ei.summarize([good])) == []


def test_intake_prompt_redirects_output_and_forbids_pipeline_folder():
    case = ei.load_cases(ei.GOLDEN_DIR, ["mod-3"])[0]
    prompt = ei.intake_prompt(case, "runs/eval/2026-01-01-0000/mod-3-brief.json")
    assert "evals/cr_golden/mod-3.md" in prompt
    assert "runs/eval/2026-01-01-0000/mod-3-brief.json" in prompt
    assert "Do not call Jira" in prompt
    assert "runs/MOD-3/" in prompt


def test_brief_schema_arg_drops_metadata():
    schema = json.loads(ei.brief_schema_arg())
    assert "$schema" not in schema and "$id" not in schema
    assert schema["required"]
