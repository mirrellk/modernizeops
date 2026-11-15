"""PreToolUse (Read|Write|Edit|Grep|Glob|Bash): per-agent path rules from docs/phase10-enforcement-todo.md.

  1. qa-reviewer must not read runs/*/03-build.md (Read, Grep, Glob, Bash).
  2. modernization-engineer writes only src/, tests/ and runs/<KEY>/03-build.md (Write, Edit, Bash).
  3. qa-reviewer writes only runs/<KEY>/04-review.json (Write, Edit, Bash).

Agent: the hook input's agent_type field, which Claude Code sets for calls made inside a subagent.
If no agent can be identified (main session, or an older client), the call is allowed and logged
to logs/agent-paths-YYYY-MM-DD.jsonl.

CR key: the active run, i.e. the runs/<KEY>/ whose STATUS.log the coordinator wrote last. It never
comes from the agent's own input, and neither restricted agent can write STATUS.log.

Bash: best-effort parsing. Write targets are taken from redirects and from file-changing commands
(rm, mv, cp, touch, mkdir, tee, sed -i, Set-Content, ...). Reads of the build note are caught when
the command names it, uses a wildcard under runs/, or runs a recursive search whose scope holds a
build note. Commands that cannot be parsed are judged on their tokens, so odd syntax tends to be
blocked rather than allowed. Fails closed for the two restricted agents.
"""

from __future__ import annotations

import fnmatch
import re
import shlex
from pathlib import Path

from _common import (
    TOKEN_RE,
    active_cr_key,
    agent_name,
    base_dir,
    deny,
    log_jsonl,
    norm,
    project_dir,
    read_input,
    rel_parts,
    resolve,
    tool_input,
    utc_now,
)

QA = "qa-reviewer"
ENGINEER = "modernization-engineer"
BUILD_NOTE = "03-build.md"
RESTRICTED = (QA, ENGINEER)

SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;|\n]")
REDIRECT_RE = re.compile(r"(?:\d|&)?>>?\s*(\"[^\"]*\"|'[^']*'|[^\s;|&<>]+)")
RUNS_WILDCARD_RE = re.compile(r"runs[\\/][^\s;|&]*[*?\[]", re.IGNORECASE)
IGNORED_TARGETS = {"/dev/null", "nul", "$null", "/dev/stdout", "/dev/stderr"}

# File-changing commands: every non-option argument is a write target ...
WRITE_ALL_ARGS = {
    "rm", "rmdir", "del", "erase", "unlink", "touch", "truncate", "mkdir", "md", "chmod",
    "mv", "move", "move-item", "mi", "rename-item", "rni", "ren", "tee", "tee-object",
    "remove-item", "ri", "new-item", "ni", "set-content", "sc", "add-content", "ac",
    "out-file", "clear-content", "clc",
}
# ... or only the destination (last argument).
WRITE_LAST_ARG = {"cp", "copy", "copy-item", "cpi", "install", "rsync"}
IN_PLACE_EDITORS = {"sed", "perl"}
# PowerShell parameters whose value is not a path.
VALUE_PARAMS = {"-value", "-encoding", "-inputobject", "-itemtype", "-filter", "-include", "-exclude"}

SEARCH_FILTER_FLAGS = ("-g", "--glob", "-t", "--type", "--include", "--type-add", "--iglob")


# ---------------------------------------------------------------- shell parsing


def _strip(token: str) -> str:
    return token.strip().strip("\"'")


def _segments(command: str) -> list[list[str]]:
    out = []
    for seg in SEGMENT_SPLIT_RE.split(command):
        seg = REDIRECT_RE.sub(" ", seg)
        try:
            tokens = shlex.split(seg, posix=False)
        except ValueError:
            tokens = seg.split()
        tokens = [_strip(t) for t in tokens if _strip(t)]
        while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
            tokens.pop(0)  # leading VAR=value assignments
        if tokens:
            out.append(tokens)
    return out


def _cmd_name(token: str) -> str:
    name = re.split(r"[\\/]", token)[-1].lower()
    return name.removesuffix(".exe")


def _non_options(args: list[str]) -> list[str]:
    result, skip = [], False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg.lower() in VALUE_PARAMS or arg == "-e":
            skip = True
            continue
        if arg.startswith("-") and len(arg) > 1:
            continue
        result.append(arg)
    return result


def bash_write_targets(command: str) -> list[str]:
    targets = [_strip(m.group(1)) for m in REDIRECT_RE.finditer(command)]
    for tokens in _segments(command):
        name, args = _cmd_name(tokens[0]), tokens[1:]
        if name in WRITE_ALL_ARGS:
            targets += _non_options(args)
        elif name in WRITE_LAST_ARG:
            targets += _non_options(args)[-1:]
        elif name in IN_PLACE_EDITORS and any(
            a.startswith(("-i", "-pi")) or a == "--in-place" for a in args
        ):
            targets += _non_options(args)[1:] if "-e" not in args else _non_options(args)
    return [t for t in targets if t and t.lower() not in IGNORED_TARGETS]


# ---------------------------------------------------------------- read rule (qa-reviewer)


def is_build_note(path: Path, project: Path) -> bool:
    parts = rel_parts(path, project)
    return (
        parts is not None
        and len(parts) == 3
        and parts[0] == norm("runs")[0]
        and parts[2] == norm(BUILD_NOTE)[0]
    )


def _build_notes(project: Path) -> list[Path]:
    return [p.resolve() for p in (project / "runs").glob(f"*/{BUILD_NOTE}")]


def _scope_holds_note(scope: Path, project: Path) -> list[Path]:
    if scope.is_file() or not scope.exists():
        return [scope] if is_build_note(scope, project) else []
    return [n for n in _build_notes(project) if rel_parts(n, scope) is not None]


def _expand_braces(pattern: str) -> list[str]:
    m = re.search(r"\{([^{}]*)\}", pattern)
    if not m:
        return [pattern]
    head, tail = pattern[: m.start()], pattern[m.end() :]
    return [x for alt in m.group(1).split(",") for x in _expand_braces(head + alt + tail)]


def _glob_hits(glob: str, note: Path, scope: Path) -> bool:
    negated = glob.startswith("!")
    rel = note.relative_to(scope).as_posix() if note.is_relative_to(scope) else note.name
    hit = any(
        fnmatch.fnmatch(note.name, p) or fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p.removeprefix("**/"))
        for p in _expand_braces(glob.lstrip("!"))
    )
    return not hit if negated else hit


def _grep_reaches_note(ti: dict, base: Path, project: Path) -> bool:
    path = ti.get("path")
    scope = resolve(path if isinstance(path, str) and path else ".", base)
    notes = _scope_holds_note(scope, project)
    if not notes:
        return False
    file_type = ti.get("type")
    if isinstance(file_type, str) and file_type and file_type.lower() not in ("md", "markdown"):
        return False
    glob = ti.get("glob")
    if isinstance(glob, str) and glob:
        return any(_glob_hits(glob, n, scope if scope.is_dir() else scope.parent) for n in notes)
    return True


def _bash_reads_note(command: str, base: Path, project: Path) -> bool:
    if RUNS_WILDCARD_RE.search(command):
        return True
    for tokens in _segments(command):
        name, args = _cmd_name(tokens[0]), tokens[1:]
        if name == "git" and args[:1] == ["grep"]:
            name, args = "rg", args[1:]
        recursive = (
            name in ("rg", "ag")
            or (name in ("grep", "egrep", "fgrep") and any(
                a in ("--recursive", "--dereference-recursive")
                or (a.startswith("-") and not a.startswith("--") and ("r" in a or "R" in a))
                for a in args
            ))
            or (name == "findstr" and any(a.lower() == "/s" for a in args))
            or (name == "find" and any(a in ("-exec", "-execdir", "-ok") for a in args))
            or (name == "find" and "xargs" in command)
        )
        if not recursive:
            continue
        if name != "find" and any(a.split("=")[0] in SEARCH_FILTER_FLAGS for a in args):
            continue  # restricted by file filter; best effort
        paths = [a for a in _non_options(args) if not a.startswith("/") or name != "findstr"]
        if name != "find":
            paths = paths[1:]  # first non-option is the search pattern
        else:
            paths = paths[:1]
        for p in paths or ["."]:
            if _scope_holds_note(resolve(p, base), project):
                return True
    return False


def qa_read_violation(tool: str, ti: dict, base: Path, project: Path) -> str | None:
    msg = f"{tool} blocked for {QA}: the reviewer must not read runs/*/{BUILD_NOTE} (the author's narrative)."
    fields = " ".join(str(ti.get(k, "")) for k in ("file_path", "path", "pattern", "glob", "command"))
    if "03-build" in fields.lower():
        return msg
    if tool == "Read" and isinstance(ti.get("file_path"), str):
        if is_build_note(resolve(ti["file_path"], base), project):
            return msg
    elif tool == "Grep":
        if _grep_reaches_note(ti, base, project):
            return msg + " Narrow the search with path, glob or type so it excludes runs/*/03-build.md."
    elif (
        tool == "Bash"
        and isinstance(ti.get("command"), str)
        and _bash_reads_note(ti["command"], base, project)
    ):
        return msg
    return None


# ---------------------------------------------------------------- write rules


def write_allowed(agent: str, parts: tuple[str, ...] | None, key: str | None) -> bool:
    if parts is None:
        return False
    if agent == ENGINEER:
        if len(parts) >= 2 and parts[0] in (norm("src")[0], norm("tests")[0]):
            return True
        return key is not None and parts == norm("runs", key, BUILD_NOTE)
    if agent == QA:
        return key is not None and parts == norm("runs", key, "04-review.json")
    return True


def scope_text(agent: str, key: str | None) -> str:
    k = key or "<no active CR: no runs/*/STATUS.log>"
    if agent == ENGINEER:
        return f"src/, tests/ and runs/{k}/{BUILD_NOTE}"
    return f"runs/{k}/04-review.json"


def write_violation(agent: str, tool: str, ti: dict, base: Path, project: Path) -> str | None:
    if tool in ("Write", "Edit"):
        targets = [ti.get("file_path")]
    elif tool == "Bash":
        command = ti.get("command")
        targets = bash_write_targets(command) if isinstance(command, str) else []
    else:
        return None
    key = active_cr_key(project)
    for target in targets:
        if not isinstance(target, str) or not target:
            return f"{tool} blocked for {agent}: no target path given."
        path = resolve(target, base)
        if not write_allowed(agent, rel_parts(path, project), key):
            return f"{tool} blocked for {agent}: {path} is outside its write scope ({scope_text(agent, key)})."
    return None


# ---------------------------------------------------------------- entry point


def check(data: dict) -> str | None:
    agent = agent_name(data)
    tool = data.get("tool_name", "")
    ti = tool_input(data)
    if agent is None:
        summary = {k: TOKEN_RE.sub("***", str(v))[:300] for k, v in ti.items()
                   if k in ("file_path", "path", "pattern", "glob", "command")}
        log_jsonl("agent-paths", {
            "time": utc_now().isoformat(),
            "session_id": data.get("session_id"),
            "tool_name": tool,
            "decision": "allow",
            "reason": "agent not identified",
            "target": summary,
        })
        return None
    if agent not in RESTRICTED:
        return None
    project, base = project_dir(), base_dir(data)
    if agent == QA:
        reason = qa_read_violation(tool, ti, base, project)
        if reason:
            return reason
    return write_violation(agent, tool, ti, base, project)


def main() -> None:
    try:
        data = read_input()
    except Exception as exc:  # noqa: BLE001 - fail closed on any parse error
        deny(f"agent_paths could not parse the hook input ({exc}); blocked.")
    try:
        reason = check(data)
    except Exception as exc:  # noqa: BLE001 - fail closed for restricted agents
        if agent_name(data) in RESTRICTED:
            deny(f"agent_paths failed ({type(exc).__name__}: {exc}); blocked for {agent_name(data)}.")
        return
    if reason:
        deny(reason)


if __name__ == "__main__":
    main()
