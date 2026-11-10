"""Validate a change-request brief against schemas/cr_brief.schema.json and the corpus.

Usage:
    uv run python .claude/skills/cr-brief/scripts/validate_brief.py runs/MOD-3/01-brief.json
    uv run python .claude/skills/cr-brief/scripts/validate_brief.py brief.json --schema other.json

Checks, in order:
    1. JSON Schema (structure, patterns, ready/missing_information consistency).
    2. Semantic checks against the corpus:
       - every program maps to exactly one source file in corpus/legacy/INVENTORY.md;
       - every name in fields[] exists in corpus/standards/data-dictionary.md
         (new_fields[] holds proposed fields that do not exist yet and is not checked);
       - ready=true is invalid while missing_information is non-empty.

Prints one JSON object to stdout:
    {"file": "...", "valid": true|false, "errors": [{"path": "...", "message": "..."}]}

Exit codes: 0 valid, 1 schema or semantic errors, 2 the brief, schema, inventory or
data dictionary could not be read.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SCHEMA = REPO_ROOT / "schemas" / "cr_brief.schema.json"
DEFAULT_INVENTORY = REPO_ROOT / "corpus" / "legacy" / "INVENTORY.md"
DEFAULT_DICTIONARY = REPO_ROOT / "corpus" / "standards" / "data-dictionary.md"

# Inventory table row: | PROGRAM-ID | Source | ... |
_INVENTORY_ROW = re.compile(r"^\|\s*([A-Z][A-Z0-9#]{0,7})\s*\|\s*([^|]+?)\s*\|")
_BACKTICKED = re.compile(r"`([^`]+)`")


def _path(parts) -> str:
    return "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in parts)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def load_inventory(text: str) -> dict[str, list[str]]:
    """Map each PROGRAM-ID in the inventory table to the source files that declare it."""
    sources: dict[str, list[str]] = defaultdict(list)
    for line in text.splitlines():
        match = _INVENTORY_ROW.match(line)
        if match:
            sources[match.group(1)].append(match.group(2))
    return dict(sources)


def load_dictionary_fields(text: str) -> set[str]:
    """Collect every backticked name in the 'Field' column of every data-dictionary table."""
    fields: set[str] = set()
    field_col: int | None = None
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            field_col = None
            continue
        cells = _cells(line)
        if field_col is None:
            field_col = cells.index("Field") if "Field" in cells else None
            continue
        if field_col < len(cells):
            fields.update(_BACKTICKED.findall(cells[field_col]))
    return fields


def validate(brief: object, schema: dict) -> list[dict[str, str]]:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(brief), key=lambda e: list(map(str, e.absolute_path)))
    return [{"path": _path(e.absolute_path), "message": e.message} for e in errors]


def validate_semantics(
    brief: object, inventory: dict[str, list[str]], dictionary_fields: set[str]
) -> list[dict[str, str]]:
    """Corpus checks the schema cannot express. Tolerates malformed briefs (schema reports those)."""
    if not isinstance(brief, dict):
        return []
    errors: list[dict[str, str]] = []

    programs = brief.get("programs")
    for i, program in enumerate(programs if isinstance(programs, list) else []):
        if not isinstance(program, str):
            continue
        found = inventory.get(program, [])
        if not found:
            errors.append({
                "path": f"$.programs[{i}]",
                "message": f"program {program!r} is not a PROGRAM-ID in corpus/legacy/INVENTORY.md",
            })
        elif len(found) > 1:
            errors.append({
                "path": f"$.programs[{i}]",
                "message": (
                    f"program {program!r} maps to {len(found)} source files in "
                    f"corpus/legacy/INVENTORY.md ({'; '.join(found)}); it must map to exactly one"
                ),
            })

    fields = brief.get("fields")
    for i, field in enumerate(fields if isinstance(fields, list) else []):
        if isinstance(field, str) and field not in dictionary_fields:
            errors.append({
                "path": f"$.fields[{i}]",
                "message": f"field {field!r} is not in corpus/standards/data-dictionary.md",
            })

    missing = brief.get("missing_information")
    if brief.get("ready") is True and isinstance(missing, list) and missing:
        errors.append({
            "path": "$.ready",
            "message": f"ready is true but missing_information has {len(missing)} item(s)",
        })
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("brief", type=Path, help="Path to the brief JSON file")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA, help="Schema to validate against")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY, help="Program inventory")
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY, help="Data dictionary")
    args = parser.parse_args(argv)

    result: dict = {"file": str(args.brief), "valid": False, "errors": []}
    try:
        schema = json.loads(args.schema.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        brief = json.loads(args.brief.read_text(encoding="utf-8"))
        inventory = load_inventory(args.inventory.read_text(encoding="utf-8"))
        dictionary_fields = load_dictionary_fields(args.dictionary.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result["errors"] = [{"path": "$", "message": f"cannot read input: {exc}"}]
        print(json.dumps(result, indent=2))
        return 2
    except SchemaError as exc:
        result["errors"] = [{"path": "$", "message": f"invalid schema: {exc}"}]
        print(json.dumps(result, indent=2))
        return 2

    if not inventory or not dictionary_fields:
        empty = "inventory" if not inventory else "data dictionary"
        result["errors"] = [{"path": "$", "message": f"cannot read input: no entries parsed from the {empty}"}]
        print(json.dumps(result, indent=2))
        return 2

    result["errors"] = validate(brief, schema) + validate_semantics(brief, inventory, dictionary_fields)
    result["valid"] = not result["errors"]
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
