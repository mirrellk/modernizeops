"""PostToolUse (all tools): append one JSON line per tool call to logs/audit-YYYY-MM-DD.jsonl (UTC).

Fields: time, session_id, agent (when known), tool_name, tool_input, success.
tool_input is redacted: any value whose key contains token, secret, password or key is masked, and
token-like strings anywhere are masked. Long strings are truncated. Never blocks a call.
"""

from __future__ import annotations

import re
import sys
from typing import Any

from _common import TOKEN_RE, agent_name, log_jsonl, read_input, utc_now

MASK = "***"
SENSITIVE_KEY_RE = re.compile(r"token|secret|password|key", re.IGNORECASE)
MAX_STRING = 1000


def redact(value: Any, key: str | None = None) -> Any:
    if key is not None and SENSITIVE_KEY_RE.search(key):
        return MASK
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = TOKEN_RE.sub(MASK, value)
        if len(value) > MAX_STRING:
            value = f"{value[:MAX_STRING]}...[+{len(value) - MAX_STRING} chars]"
    return value


def succeeded(response: Any) -> bool:
    if isinstance(response, dict):
        if "success" in response:
            return bool(response["success"])
        for flag in ("is_error", "isError"):
            if flag in response:
                return not response[flag]
        if response.get("error"):
            return False
    return True


def main() -> None:
    try:
        data = read_input()
        log_jsonl("audit", {
            "time": utc_now().isoformat(),
            "session_id": data.get("session_id"),
            "agent": agent_name(data),
            "tool_name": data.get("tool_name"),
            "tool_input": redact(data.get("tool_input")),
            "success": succeeded(data.get("tool_response")),
        })
    except Exception as exc:  # noqa: BLE001 - never block a tool call over logging
        print(f"audit_log: could not write audit record ({type(exc).__name__}: {exc})", file=sys.stderr)


if __name__ == "__main__":
    main()
