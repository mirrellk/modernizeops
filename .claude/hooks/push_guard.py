"""PreToolUse (Bash | PowerShell): block anything that would update main on a remote, or merge a PR.

Denies:
  - git push whose refspec destination is main (main, +main, HEAD:main, x:refs/heads/main, :main),
    including -u/--set-upstream forms and git -C <dir> / -c k=v global options
  - git push --all / --mirror (they update main too)
  - git push with no refspec, or a HEAD/@ refspec, while the current branch is main
    (or when the current branch cannot be determined)
  - gh pr merge
  - gh api calls to a pulls/<n>/merge endpoint

Both shells: commands are split on ; | && || newlines, ( ) and { }; leading VAR=value assignments
and wrappers (env, command, exec, time, nohup, sudo) are skipped; git.exe and full paths count as git.
Nested shells are checked recursively: bash/sh -c, cmd /c, powershell/pwsh -Command or
-EncodedCommand, Invoke-Expression/iex, and Start-Process/saps/start (FilePath + ArgumentList).

PowerShell mode (tool_name PowerShell): backtick is the escape character, & and . at the start of
a command are the call / dot-source operators, and cmdlet and parameter names are case-insensitive
and may be abbreviated.

Fails closed: errors, unparseable commands that mention push or merge, and nesting deeper than
MAX_DEPTH are blocked.
"""

from __future__ import annotations

import base64
import re
import shlex
from pathlib import Path

from _common import base_dir, current_branch, deny, read_input, resolve, tool_input

PROTECTED = "main"
MAX_DEPTH = 4
SEPARATOR_CHARS = set(";&|(){}\n")
WRAPPERS = {"env", "command", "exec", "time", "nohup", "sudo", "builtin"}
POSIX_SHELLS = {"bash", "sh", "zsh", "dash"}
PS_SHELLS = {"powershell", "pwsh"}
START_PROCESS = {"start-process", "saps", "start"}
INVOKE_EXPRESSION = {"invoke-expression", "iex"}
ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
MERGE_ENDPOINT_RE = re.compile(r"(?:^|/)pulls/[^/\s]+/merge/?(?:\?.*)?$")
MENTIONS_RE = re.compile(r"\b(push|merge)\b", re.IGNORECASE)

# git global options that take a separate value.
GIT_GLOBAL_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
# git push options that take a separate value.
PUSH_WITH_ARG = {"--repo", "-o", "--push-option", "--receive-pack", "--exec", "--recurse-submodules"}

# Start-Process parameters (aliases mapped to the canonical name); True = takes a value.
START_PROCESS_PARAMS = {
    "filepath": True,
    "argumentlist": True,
    "args": True,
    "workingdirectory": True,
    "credential": True,
    "verb": True,
    "windowstyle": True,
    "redirectstandardinput": True,
    "redirectstandardoutput": True,
    "redirectstandarderror": True,
    "environment": True,
    "wait": False,
    "nonewwindow": False,
    "passthru": False,
    "loaduserprofile": False,
    "usenewenvironment": False,
}
# powershell.exe / pwsh parameters that take a value (other than -Command/-EncodedCommand/-File).
PS_VALUE_PARAMS = {
    "executionpolicy", "ex", "ep", "windowstyle", "w", "configurationname", "workingdirectory", "wd",
    "outputformat", "o", "of", "inputformat", "if", "version", "psconsolefile", "settingsfile",
}


class Unparseable(Exception):
    pass


def program(token: str) -> str:
    """Basename without .exe, lower-cased: /usr/bin/git, C:\\Git\\cmd\\git.exe -> git."""
    name = re.split(r"[\\/]", token.strip())[-1].lower()
    return name.removesuffix(".exe")


def segments(command: str, ps: bool) -> list[list[str]]:
    lexer = shlex.shlex(command.replace("\r", "\n"), posix=True, punctuation_chars=";&|(){}")
    lexer.whitespace = " \t"
    lexer.whitespace_split = True
    lexer.commenters = ""
    if ps:
        lexer.escape = "`"
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise Unparseable(str(exc)) from exc

    out: list[list[str]] = [[]]
    for token in tokens:
        if ps and token == "&" and not out[-1]:
            continue  # call operator: & git push ...
        if token and set(token) <= SEPARATOR_CHARS:
            out.append([])
        elif "\n" in token:
            first, *rest = token.split("\n")
            if first:
                out[-1].append(first)
            for part in rest:
                out.append([part] if part else [])
        else:
            out[-1].append(token)
    return [seg for seg in out if seg]


def strip_prefix(tokens: list[str], ps: bool) -> list[str]:
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if ps and tok == ".":
            i += 1
            continue
        if ASSIGNMENT_RE.match(tok) or program(tok) in WRAPPERS or (tok.startswith("-") and i > 0):
            i += 1
            continue
        break
    return tokens[i:]


def normalise_ref(ref: str) -> str:
    for prefix in ("refs/heads/", "heads/"):
        if ref.startswith(prefix):
            return ref[len(prefix) :]
    return ref


def check_push(args: list[str], workdir: Path) -> str | None:
    positionals: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            positionals.extend(args[i + 1 :])
            break
        if arg in ("--all", "--mirror", "--branches"):
            return f"git push {arg} would update {PROTECTED}"
        if arg in PUSH_WITH_ARG:
            i += 2
            continue
        if arg.startswith("-"):
            i += 1
            continue
        positionals.append(arg)
        i += 1

    refspecs = positionals[1:]
    branch = None
    needs_branch = not refspecs or any(r.lstrip("+") in ("HEAD", "@") for r in refspecs)
    if needs_branch:
        branch = current_branch(workdir)
        if branch is None:
            return "git push without an explicit branch, and the current branch could not be determined"

    if not refspecs:
        if branch == PROTECTED:
            return f"bare git push while the current branch is {PROTECTED}"
        return None

    for spec in refspecs:
        spec = spec.lstrip("+")
        src, _, dst = spec.partition(":")
        target = dst if ":" in spec else src
        if target in ("HEAD", "@"):
            target = branch or ""
        if normalise_ref(target) == PROTECTED:
            return f"refspec {spec!r} updates {PROTECTED}"
    return None


def check_git(tokens: list[str], base: Path) -> str | None:
    workdir = base
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok in GIT_GLOBAL_WITH_ARG:
            if tok == "-C" and i + 1 < len(tokens):
                workdir = resolve(tokens[i + 1], workdir)
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        break
    # Lower-cased: on Windows git can resolve git-PUSH to git-push.exe on a case-insensitive disk.
    if i < len(tokens) and tokens[i].lower() == "push":
        return check_push(tokens[i + 1 :], workdir)
    return None


def check_gh(tokens: list[str]) -> str | None:
    positionals = [t.lower() for t in tokens[1:] if not t.startswith("-")]
    if positionals[:2] == ["pr", "merge"]:
        return "gh pr merge merges a pull request"
    if positionals[:1] == ["api"]:
        for tok in tokens[1:]:
            value = tok.split("=", 1)[-1] if tok.startswith("--") else tok
            if MERGE_ENDPOINT_RE.search(value):
                return f"gh api call to merge endpoint {value!r}"
    return None


def ps_param(token: str) -> tuple[str, str | None] | None:
    """'-ArgumentList:x' -> ('argumentlist', 'x'); '-Wait' -> ('wait', None); 'git' -> None."""
    if not token.startswith("-") or len(token) < 2:
        return None
    name, sep, value = token[1:].partition(":")
    return name.lower(), (value if sep else None)


def resolve_start_process_param(name: str) -> str | None:
    if name in START_PROCESS_PARAMS:
        return name
    matches = {p for p in START_PROCESS_PARAMS if p.startswith(name)}
    if matches <= {"argumentlist", "args"} and matches:
        return "argumentlist"
    return matches.pop() if len(matches) == 1 else None


def check_start_process(tokens: list[str], base: Path, depth: int) -> str | None:
    file_path: str | None = None
    arg_list: list[str] = []
    workdir = base
    positionals: list[str] = []
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        param = ps_param(tok)
        if param is None:
            positionals.append(tok)
            i += 1
            continue
        name = resolve_start_process_param(param[0])
        takes_value = START_PROCESS_PARAMS.get(name or "", True)  # unknown: assume it takes a value
        value = param[1]
        i += 1
        if takes_value and value is None:
            if name == "argumentlist":
                # May span several tokens: -ArgumentList push, origin, main
                start = i
                while i < len(tokens) and ps_param(tokens[i]) is None:
                    i += 1
                value = " ".join(tokens[start:i])
            elif i < len(tokens):
                value = tokens[i]
                i += 1
        if name == "filepath":
            file_path = value
        elif name == "argumentlist" and value:
            arg_list.append(value)
        elif name == "workingdirectory" and value:
            workdir = resolve(value, base)

    if file_path is None and positionals:
        file_path, positionals = positionals[0], positionals[1:]
    arg_list.extend(positionals)
    if not file_path:
        return None
    script = " ".join([shlex.quote(file_path), *(a.replace(",", " ") for a in arg_list)])
    return check_command(script, workdir, ps=False, depth=depth + 1)


def check_powershell_exe(tokens: list[str], base: Path, depth: int) -> str | None:
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        param = ps_param(tok) if tok.startswith("-") else (ps_param("-" + tok[1:]) if tok.startswith("/") else None)
        if param is None:
            return check_command(" ".join(tokens[i:]), base, ps=True, depth=depth + 1)
        name, value = param
        if name in ("c", "command") or (len(name) >= 3 and "command".startswith(name)):
            script = value if value is not None else " ".join(tokens[i + 1 :])
            return check_command(script, base, ps=True, depth=depth + 1) if script != "-" else None
        if name in ("e", "ec") or (len(name) >= 2 and name.startswith("en") and "encodedcommand".startswith(name)):
            encoded = value if value is not None else (tokens[i + 1] if i + 1 < len(tokens) else "")
            try:
                script = base64.b64decode(encoded, validate=True).decode("utf-16-le")
            except ValueError as exc:
                raise Unparseable("bad -EncodedCommand") from exc
            return check_command(script, base, ps=True, depth=depth + 1)
        if name in ("f", "file") or (len(name) >= 2 and "file".startswith(name)):
            return None  # runs a script file; its contents are not visible here
        i += 2 if name in PS_VALUE_PARAMS and value is None else 1
    return None


def check_tokens(tokens: list[str], base: Path, ps: bool, depth: int) -> str | None:
    prog = program(tokens[0])
    rest = tokens[1:]
    if prog in POSIX_SHELLS:
        if "-c" in rest:
            idx = rest.index("-c")
            if idx + 1 < len(rest):
                return check_command(rest[idx + 1], base, ps=False, depth=depth + 1)
        return None
    if prog == "cmd":
        for idx, tok in enumerate(rest):
            if tok.lower() in ("/c", "/k"):
                return check_command(" ".join(rest[idx + 1 :]), base, ps=False, depth=depth + 1)
        return None
    if prog in PS_SHELLS:
        return check_powershell_exe(tokens, base, depth)
    if prog in INVOKE_EXPRESSION:
        args = [t for t in rest if (p := ps_param(t)) is None or not "command".startswith(p[0])]
        return check_command(" ".join(args), base, ps=True, depth=depth + 1)
    if prog in START_PROCESS:
        return check_start_process(tokens, base, depth)
    if prog == "git":
        return check_git(tokens, base)
    if prog == "gh":
        return check_gh(tokens)
    return None


def check_command(command: str, base: Path, ps: bool = False, depth: int = 0) -> str | None:
    if depth > MAX_DEPTH:
        return "command nests shells too deeply to check" if MENTIONS_RE.search(command) else None
    try:
        segs = segments(command, ps)
    except Unparseable:
        if MENTIONS_RE.search(command):
            return "command could not be parsed and mentions push or merge"
        return None
    for seg in segs:
        tokens = strip_prefix(seg, ps)
        if tokens and (reason := check_tokens(tokens, base, ps, depth)):
            return reason
    return None


def main() -> None:
    try:
        data = read_input()
        command = tool_input(data).get("command")
        ps = data.get("tool_name") == "PowerShell"
        reason = check_command(command, base_dir(data), ps=ps) if isinstance(command, str) else None
    except Exception as exc:  # noqa: BLE001 - fail closed on any error
        deny(f"push_guard could not check this command ({type(exc).__name__}: {exc}); blocked.")
    if reason:
        deny(f"Blocked by push_guard: {reason}. Changes reach {PROTECTED} only through a reviewed PR.")


if __name__ == "__main__":
    main()
