"""PreToolUse (Read|Edit|Write|Bash|PowerShell): keep secrets out of tool calls.

Blocks (exit 2) when the tool input mentions a dotenv file other than the example file, an SSH
private key name, or a token-like string; and blocks Write/Edit to any path outside the repo.
Fails closed: unreadable input is blocked too.
"""

from __future__ import annotations

import json
import re

from _common import (
    TOKEN_RE,
    base_dir,
    deny,
    project_dir,
    read_input,
    rel_parts,
    resolve,
    tool_input,
)

# Built from pieces so this file does not match its own patterns.
DOTENV_RE = re.compile(r"\.en" + r"v(?![\w])(?!\.example\b)", re.IGNORECASE)
SSH_KEY_RE = re.compile(r"id_" + r"rsa", re.IGNORECASE)


def check(data: dict) -> str | None:
    tool = data.get("tool_name", "")
    ti = tool_input(data)
    text = json.dumps(ti, ensure_ascii=False)

    if DOTENV_RE.search(text):
        return f"{tool} blocked: input references a dotenv secrets file (only the example file is allowed)."
    if SSH_KEY_RE.search(text):
        return f"{tool} blocked: input references an SSH private key."
    if TOKEN_RE.search(text):
        return f"{tool} blocked: input contains a token-like string. Never put credentials in tool calls."

    if tool in ("Write", "Edit"):
        file_path = ti.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            return f"{tool} blocked: no file_path given."
        target = resolve(file_path, base_dir(data))
        if rel_parts(target, project_dir()) is None:
            return f"{tool} blocked: {target} is outside the repository {project_dir()}."
    return None


def main() -> None:
    try:
        reason = check(read_input())
    except Exception as exc:  # noqa: BLE001 - fail closed on any error
        deny(f"block_secrets could not check this call ({type(exc).__name__}: {exc}); blocked.")
    if reason:
        deny(reason)


if __name__ == "__main__":
    main()
