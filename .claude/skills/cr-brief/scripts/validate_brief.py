"""Validate a change-request brief against schemas/cr_brief.schema.json.

Usage:
    uv run python .claude/skills/cr-brief/scripts/validate_brief.py runs/MOD-3/cr_brief.json
    uv run python .claude/skills/cr-brief/scripts/validate_brief.py brief.json --schema other.json

Prints one JSON object to stdout:
    {"file": "...", "valid": true|false, "errors": [{"path": "...", "message": "..."}]}

Exit codes: 0 valid, 1 schema errors, 2 the file or schema could not be read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SCHEMA = REPO_ROOT / "schemas" / "cr_brief.schema.json"


def _path(parts) -> str:
    return "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in parts)


def validate(brief: object, schema: dict) -> list[dict[str, str]]:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(brief), key=lambda e: list(map(str, e.absolute_path)))
    return [{"path": _path(e.absolute_path), "message": e.message} for e in errors]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("brief", type=Path, help="Path to the brief JSON file")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA, help="Schema to validate against")
    args = parser.parse_args(argv)

    result: dict = {"file": str(args.brief), "valid": False, "errors": []}
    try:
        schema = json.loads(args.schema.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        brief = json.loads(args.brief.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result["errors"] = [{"path": "$", "message": f"cannot read input: {exc}"}]
        print(json.dumps(result, indent=2))
        return 2
    except SchemaError as exc:
        result["errors"] = [{"path": "$", "message": f"invalid schema: {exc}"}]
        print(json.dumps(result, indent=2))
        return 2

    result["errors"] = validate(brief, schema)
    result["valid"] = not result["errors"]
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
