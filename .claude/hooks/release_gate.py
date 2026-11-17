"""PreToolUse (create_pull_request | jira_transition_issue): release gate.

Allows the call only when, for the CR being released:
  - runs/<KEY>/01-brief.json has ready == true
  - runs/<KEY>/04-review.json has verdict == "pass"
  - design/<KEY>-design.docx exists

The CR key comes from the PR head branch (cr/<KEY>) or PR title for create_pull_request, from the
issue key for jira_transition_issue, and from the current git branch when the input has none.
Several different keys, or none, block the call. Fails closed.
"""

from __future__ import annotations

import json
from pathlib import Path

from _common import (
    CR_BRANCH_RE,
    CR_KEY_RE,
    current_branch,
    deny,
    project_dir,
    read_input,
    tool_input,
)


def candidate_keys(data: dict, project: Path) -> set[str]:
    tool = data.get("tool_name", "")
    ti = tool_input(data)
    keys: set[str] = set()

    if tool.endswith("create_pull_request"):
        head = ti.get("head")
        if isinstance(head, str) and (m := CR_BRANCH_RE.search(head.strip())):
            keys.add(m.group(1))
        title = ti.get("title")
        if isinstance(title, str):
            keys.update(CR_KEY_RE.findall(title))
    elif tool.endswith("jira_transition_issue"):
        for field in ("issue_key", "issueKey", "key"):
            value = ti.get(field)
            if isinstance(value, str) and CR_KEY_RE.fullmatch(value.strip()):
                keys.add(value.strip())

    if not keys:
        branch = current_branch(project)
        if branch and (m := CR_BRANCH_RE.search(branch)):
            keys.add(m.group(1))
    return keys


def load_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def problems_for(key: str, project: Path) -> list[str]:
    problems = []
    brief = load_json(project / "runs" / key / "01-brief.json")
    if brief is None:
        problems.append(f"runs/{key}/01-brief.json is missing or not valid JSON")
    elif brief.get("ready") is not True:
        problems.append(f"runs/{key}/01-brief.json has ready={brief.get('ready')!r}, needs true")

    review = load_json(project / "runs" / key / "04-review.json")
    if review is None:
        problems.append(f"runs/{key}/04-review.json is missing or not valid JSON")
    elif review.get("verdict") != "pass":
        problems.append(f"runs/{key}/04-review.json has verdict={review.get('verdict')!r}, needs 'pass'")

    if not (project / "design" / f"{key}-design.docx").is_file():
        problems.append(f"design/{key}-design.docx does not exist")
    return problems


def check(data: dict) -> str | None:
    project = project_dir()
    tool = data.get("tool_name", "")
    keys = candidate_keys(data, project)
    if not keys:
        return f"{tool} blocked by release gate: no CR key found in the branch name, PR title or issue key."
    if len(keys) > 1:
        return f"{tool} blocked by release gate: conflicting CR keys {sorted(keys)}."
    key = keys.pop()
    problems = problems_for(key, project)
    if problems:
        return f"{tool} blocked by release gate for {key}: " + "; ".join(problems) + "."
    return None


def main() -> None:
    try:
        reason = check(read_input())
    except Exception as exc:  # noqa: BLE001 - fail closed on any error
        deny(f"release_gate could not check this call ({type(exc).__name__}: {exc}); blocked.")
    if reason:
        deny(reason)


if __name__ == "__main__":
    main()
