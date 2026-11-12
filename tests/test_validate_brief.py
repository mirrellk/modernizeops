"""Tests for .claude/skills/cr-brief/scripts/validate_brief.py (schema + corpus semantic checks)."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".claude" / "skills" / "cr-brief" / "scripts" / "validate_brief.py"

_spec = importlib.util.spec_from_file_location("validate_brief", SCRIPT)
vb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vb)

INVENTORY = """\
# Inventory

| PROGRAM-ID | Source | Files read/written | Copybooks |
|---|---|---|---|
| CBL0001 | Labs/cbl/CBL0001.cobol | — | — |
| CBL0006 | Labs/cbl/CBL0006.cobol | — | — |
| CBL0006 | Labs/cbl/CBLC1.cobol | — | — |
"""

DICTIONARY = """\
# Dictionary

| Level | Field | PIC / USAGE | Offset |
|---|---|---|---|
| 05 | `ACCT-NO` | `X(8)` | 1 |
| 05 | `ACCT-LIMIT` | `S9(7)V99 COMP-3` | 9 |

Some prose with `NOT-A-FIELD` in backticks.

| FD | DD | Level | Field | PIC |
|---|---|---|---|---|
| `RECIN` | `DA-S-RECIN` | 01 | `INREC` | `X(80)` |
"""


def _brief(**overrides) -> dict:
    brief = {
        "cr_key": "MOD-1",
        "summary": "Flag accounts over limit.",
        "programs": ["CBL0001"],
        "fields": ["ACCT-NO", "ACCT-LIMIT"],
        "acceptance_criteria": ["OVER-LIMIT is Y when balance exceeds limit."],
        "risk": "medium",
        "pii": True,
        "missing_information": [],
        "ready": True,
    }
    brief.update(overrides)
    return brief


@pytest.fixture
def corpus(tmp_path: Path) -> tuple[Path, Path]:
    inv = tmp_path / "INVENTORY.md"
    dic = tmp_path / "data-dictionary.md"
    inv.write_text(INVENTORY, encoding="utf-8")
    dic.write_text(DICTIONARY, encoding="utf-8")
    return inv, dic


def _run(tmp_path: Path, corpus, brief: dict, capsys) -> tuple[int, dict]:
    inv, dic = corpus
    path = tmp_path / "01-brief.json"
    path.write_text(json.dumps(brief), encoding="utf-8")
    code = vb.main([str(path), "--inventory", str(inv), "--dictionary", str(dic)])
    return code, json.loads(capsys.readouterr().out)


# --- parsers -------------------------------------------------------------------------------

def test_load_inventory_groups_sources_by_program_id():
    inv = vb.load_inventory(INVENTORY)
    assert inv["CBL0001"] == ["Labs/cbl/CBL0001.cobol"]
    assert inv["CBL0006"] == ["Labs/cbl/CBL0006.cobol", "Labs/cbl/CBLC1.cobol"]
    assert "PROGRAM-ID" not in inv


def test_load_dictionary_reads_field_column_of_every_table_only():
    fields = vb.load_dictionary_fields(DICTIONARY)
    assert fields == {"ACCT-NO", "ACCT-LIMIT", "INREC"}


# --- semantic checks ------------------------------------------------------------------------

def test_valid_brief_passes(tmp_path, corpus, capsys):
    code, out = _run(tmp_path, corpus, _brief(), capsys)
    assert code == 0
    assert out == {"file": str(tmp_path / "01-brief.json"), "valid": True, "errors": []}


def test_program_with_two_source_files_is_rejected(tmp_path, corpus, capsys):
    code, out = _run(tmp_path, corpus, _brief(programs=["CBL0006"]), capsys)
    assert code == 1
    [err] = out["errors"]
    assert err["path"] == "$.programs[0]"
    assert "2 source files" in err["message"] and "CBLC1.cobol" in err["message"]


def test_unknown_program_is_rejected(tmp_path, corpus, capsys):
    code, out = _run(tmp_path, corpus, _brief(programs=["CBL0001", "NOPE01"]), capsys)
    assert code == 1
    [err] = out["errors"]
    assert err["path"] == "$.programs[1]"
    assert "not a PROGRAM-ID" in err["message"]


def test_unknown_field_is_rejected(tmp_path, corpus, capsys):
    code, out = _run(tmp_path, corpus, _brief(fields=["ACCT-NO", "VIP-FLAG"]), capsys)
    assert code == 1
    [err] = out["errors"]
    assert err["path"] == "$.fields[1]"
    assert "VIP-FLAG" in err["message"]


def test_prose_backticks_do_not_count_as_fields(tmp_path, corpus, capsys):
    code, out = _run(tmp_path, corpus, _brief(fields=["NOT-A-FIELD"]), capsys)
    assert code == 1
    assert out["errors"][0]["path"] == "$.fields[0]"


def test_ready_with_missing_information_is_rejected_semantically():
    brief = _brief(missing_information=[{"question": "Which file?", "why_it_blocks": "No program."}])
    errors = vb.validate_semantics(brief, vb.load_inventory(INVENTORY), vb.load_dictionary_fields(DICTIONARY))
    assert errors == [{"path": "$.ready", "message": "ready is true but missing_information has 1 item(s)"}]


def test_each_failure_is_its_own_error(tmp_path, corpus, capsys):
    brief = _brief(
        programs=["CBL0006", "NOPE01"],
        fields=["VIP-FLAG"],
        missing_information=[{"question": "q", "why_it_blocks": "w"}],
    )
    code, out = _run(tmp_path, corpus, brief, capsys)
    assert code == 1
    paths = [e["path"] for e in out["errors"]]
    assert {"$.programs[0]", "$.programs[1]", "$.fields[0]", "$.ready"} <= set(paths)


def test_not_ready_brief_still_checks_names(tmp_path, corpus, capsys):
    brief = _brief(
        ready=False,
        programs=["NOPE01"],
        missing_information=[{"question": "q", "why_it_blocks": "w"}],
    )
    code, out = _run(tmp_path, corpus, brief, capsys)
    assert code == 1
    assert [e["path"] for e in out["errors"]] == ["$.programs[0]"]


def test_malformed_brief_reports_schema_errors_without_crashing(tmp_path, corpus, capsys):
    code, out = _run(tmp_path, corpus, _brief(programs="CBL0001", fields=[42]), capsys)
    assert code == 1
    assert out["errors"]


def test_unreadable_inventory_exits_2(tmp_path, corpus, capsys):
    _, dic = corpus
    path = tmp_path / "01-brief.json"
    path.write_text(json.dumps(_brief()), encoding="utf-8")
    code = vb.main([str(path), "--inventory", str(tmp_path / "missing.md"), "--dictionary", str(dic)])
    assert code == 2
    assert "cannot read input" in json.loads(capsys.readouterr().out)["errors"][0]["message"]


def test_empty_dictionary_exits_2(tmp_path, corpus, capsys):
    inv, _ = corpus
    empty = tmp_path / "empty.md"
    empty.write_text("# nothing here\n", encoding="utf-8")
    path = tmp_path / "01-brief.json"
    path.write_text(json.dumps(_brief()), encoding="utf-8")
    code = vb.main([str(path), "--inventory", str(inv), "--dictionary", str(empty)])
    assert code == 2


# --- new_fields -----------------------------------------------------------------------------

NEW_FIELD = {"name": "OVER-LIMIT-O", "pic": "X(1)", "purpose": "Y when balance exceeds limit."}


def test_new_fields_are_not_checked_against_the_dictionary(tmp_path, corpus, capsys):
    code, out = _run(tmp_path, corpus, _brief(new_fields=[NEW_FIELD]), capsys)
    assert code == 0, out
    assert out["valid"] is True


def test_new_fields_is_optional(tmp_path, corpus, capsys):
    brief = _brief()
    brief.pop("new_fields", None)
    code, _ = _run(tmp_path, corpus, brief, capsys)
    assert code == 0


def test_proposed_field_in_fields_is_still_rejected(tmp_path, corpus, capsys):
    code, out = _run(tmp_path, corpus, _brief(fields=["ACCT-NO", "OVER-LIMIT-O"]), capsys)
    assert code == 1
    assert [e["path"] for e in out["errors"]] == ["$.fields[1]"]


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "OVER-LIMIT-O", "pic": "X(1)"},  # purpose missing
        {"name": "over-limit", "pic": "X(1)", "purpose": "p"},  # lowercase name
        {"name": "OVER-LIMIT-O", "pic": "", "purpose": "p"},  # empty pic
        {**NEW_FIELD, "extra": 1},  # unknown key
    ],
)
def test_malformed_new_field_fails_schema(bad, tmp_path, corpus, capsys):
    code, out = _run(tmp_path, corpus, _brief(new_fields=[bad]), capsys)
    assert code == 1
    assert all(e["path"].startswith("$.new_fields[0]") for e in out["errors"]), out


# --- analysis_notes -------------------------------------------------------------------------

NOTE = "Confirm the PRINT-REC detail-line length and byte offsets from CBL0001 source."


def test_analysis_notes_are_accepted_on_a_ready_brief(tmp_path, corpus, capsys):
    code, out = _run(tmp_path, corpus, _brief(analysis_notes=[NOTE]), capsys)
    assert code == 0, out
    assert out["valid"] is True


def test_analysis_notes_is_optional(tmp_path, corpus, capsys):
    brief = _brief()
    brief.pop("analysis_notes", None)
    code, _ = _run(tmp_path, corpus, brief, capsys)
    assert code == 0


def test_empty_analysis_notes_without_program_is_fine(tmp_path, corpus, capsys):
    brief = _brief(
        ready=False,
        programs=[],
        analysis_notes=[],
        missing_information=[{"question": "Which program?", "why_it_blocks": "No code to analyse."}],
    )
    code, out = _run(tmp_path, corpus, brief, capsys)
    assert code == 0, out


def test_analysis_notes_do_not_satisfy_not_ready_rule(tmp_path, corpus, capsys):
    # ready=false still needs a business question; notes alone never block.
    code, out = _run(tmp_path, corpus, _brief(ready=False, analysis_notes=[NOTE]), capsys)
    assert code == 1
    assert [e["path"] for e in out["errors"]] == ["$.missing_information"]


def test_analysis_notes_without_program_are_rejected(tmp_path, corpus, capsys):
    brief = _brief(
        ready=False,
        programs=[],
        analysis_notes=[NOTE],
        missing_information=[{"question": "Which program?", "why_it_blocks": "No code to analyse."}],
    )
    code, out = _run(tmp_path, corpus, brief, capsys)
    assert code == 1
    [err] = out["errors"]
    assert err["path"] == "$.analysis_notes"
    assert "programs is empty" in err["message"]


@pytest.mark.parametrize("bad", [[""], [42], "a single string", [{"note": "x"}]])
def test_malformed_analysis_notes_fail_schema(bad, tmp_path, corpus, capsys):
    code, out = _run(tmp_path, corpus, _brief(analysis_notes=bad), capsys)
    assert code == 1
    assert all(e["path"].startswith("$.analysis_notes") for e in out["errors"]), out


# --- real corpus ----------------------------------------------------------------------------

SKILL_MD = REPO_ROOT / ".claude" / "skills" / "cr-brief" / "SKILL.md"


def _skill_examples() -> list[dict]:
    blocks = re.findall(r"```json\n(.*?)\n```", SKILL_MD.read_text(encoding="utf-8"), re.DOTALL)
    return [json.loads(b) for b in blocks]


@pytest.mark.parametrize("example", _skill_examples(), ids=lambda e: e["cr_key"])
def test_skill_examples_are_valid_against_schema_and_corpus(example, tmp_path, capsys):
    path = tmp_path / "01-brief.json"
    path.write_text(json.dumps(example), encoding="utf-8")
    code = vb.main([str(path)])
    out = json.loads(capsys.readouterr().out)
    assert code == 0, out["errors"]


def test_skill_has_both_examples():
    assert [e["cr_key"] for e in _skill_examples()] == ["MOD-101", "MOD-3"]



def test_real_corpus_parses_and_flags_cbl0006():
    inv = vb.load_inventory(vb.DEFAULT_INVENTORY.read_text(encoding="utf-8"))
    fields = vb.load_dictionary_fields(vb.DEFAULT_DICTIONARY.read_text(encoding="utf-8"))
    assert len(inv["CBL0006"]) == 2
    assert len(inv["CBL0001"]) == 1
    assert {"ACCT-NO", "ACCT-LIMIT", "ACCT-BALANCE", "INREC", "PRINT-REC"} <= fields
