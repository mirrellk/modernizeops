"""Shared helpers for the ModernizeOps Claude Code hooks (stdlib only).

Hook scripts read one JSON object from stdin. PreToolUse hooks block a call by exiting 2 with the
reason on stderr. Patterns that would match their own source text are built from pieces so these
files stay editable while the hooks are active.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

CR_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
CR_BRANCH_RE = re.compile(r"(?:^|[/:])cr/([A-Z][A-Z0-9]+-\d+)$")

# Token-like strings: a known prefix followed by a realistic run of token characters.
TOKEN_RE = re.compile(
    r"(?:ghp_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-ant-[A-Za-z0-9_\-]{20,}"
    r"|ATATT[A-Za-z0-9_\-=]{20,})"
)


def project_dir() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env).resolve() if env else Path(__file__).resolve().parents[2]


def read_input() -> dict[str, Any]:
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    if not isinstance(data, dict):
        raise TypeError("hook input must be a JSON object")
    return data


def deny(reason: str) -> NoReturn:
    print(reason, file=sys.stderr)
    sys.exit(2)


def tool_input(data: dict[str, Any]) -> dict[str, Any]:
    ti = data.get("tool_input")
    return ti if isinstance(ti, dict) else {}


def agent_name(data: dict[str, Any]) -> str | None:
    """Subagent name from the hook input (Claude Code sets agent_type inside a subagent)."""
    for field in ("agent_type", "agent_name", "subagent_type"):
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            # Plugin agents arrive as "plugin:name".
            return value.strip().rsplit(":", 1)[-1]
    return None


def base_dir(data: dict[str, Any]) -> Path:
    cwd = data.get("cwd")
    return Path(cwd) if isinstance(cwd, str) and cwd else project_dir()


def resolve(path_str: str, base: Path) -> Path:
    p = Path(path_str.strip().strip("\"'")).expanduser()
    if not p.is_absolute():
        p = base / p
    return p.resolve(strict=False)


def rel_parts(path: Path, root: Path) -> tuple[str, ...] | None:
    """Case-normalised path parts of `path` relative to `root`, or None if outside it."""
    p = Path(os.path.normcase(str(path)))
    r = Path(os.path.normcase(str(root)))
    if p == r:
        return ()
    if not p.is_relative_to(r):
        return None
    return p.relative_to(r).parts


def norm(*parts: str) -> tuple[str, ...]:
    return tuple(os.path.normcase(part) for part in parts)


def utc_now() -> datetime:
    return datetime.now(UTC)


def log_jsonl(prefix: str, record: dict[str, Any]) -> None:
    logs = project_dir() / "logs"
    logs.mkdir(exist_ok=True)
    target = logs / f"{prefix}-{utc_now():%Y-%m-%d}.jsonl"
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def active_cr_key(project: Path) -> str | None:
    """The active run is the runs/<KEY>/ whose STATUS.log the coordinator touched last.

    Agents under path rules cannot write STATUS.log, so they cannot change which CR is active.
    """
    logs = [p for p in (project / "runs").glob("*/STATUS.log") if CR_KEY_RE.fullmatch(p.parent.name)]
    if not logs:
        return None
    return max(logs, key=lambda p: p.stat().st_mtime).parent.name


def current_branch(project: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(project), "branch", "--show-current"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    branch = out.stdout.strip()
    return branch if out.returncode == 0 and branch else None
