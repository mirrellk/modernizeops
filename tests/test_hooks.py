"""Tests for the Claude Code hooks in .claude/hooks/.

Each hook runs as a subprocess with hook JSON on stdin and CLAUDE_PROJECT_DIR pointing at a
throwaway repo in tmp_path. Secret-looking strings are built from pieces so this file does not
trip block_secrets when it is edited.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / ".claude" / "hooks"

DOTENV = ".en" + "v"
SSH_KEY = "id_" + "rsa"
GH_TOKEN = "gh" + "p_" + "A1b2C3d4" * 5
ANT_KEY = "sk-" + "ant-" + "x9" * 15


def run_hook(name: str, payload: dict | str, project: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(HOOKS / name)],
        input=stdin,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=project,
        timeout=60,
    )


def call(tool: str, project: Path, agent: str | None = None, **tool_input) -> dict:
    payload = {
        "session_id": "test-session",
        "cwd": str(project),
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
    }
    if agent:
        payload["agent_type"] = agent
    return payload


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "design").mkdir()
    return tmp_path


def make_run(repo: Path, key: str, *, ready=True, verdict="pass", docx=True, status=True) -> Path:
    run = repo / "runs" / key
    run.mkdir(parents=True, exist_ok=True)
    (run / "01-brief.json").write_text(json.dumps({"cr_key": key, "ready": ready}), encoding="utf-8")
    if verdict is not None:
        (run / "04-review.json").write_text(json.dumps({"verdict": verdict}), encoding="utf-8")
    if docx:
        (repo / "design" / f"{key}-design.docx").write_bytes(b"PK")
    if status:
        (run / "STATUS.log").write_text(f"2026-11-14T10:00:00Z | intake | ok {key}\n", encoding="utf-8")
    return run


def touch_status(run: Path) -> None:
    """Make this run the active one (newest STATUS.log)."""
    log = run / "STATUS.log"
    future = time.time() + 60
    os.utime(log, (future, future))


# ------------------------------------------------------------------ block_secrets


@pytest.mark.parametrize(
    "tool,tool_input",
    [
        ("Read", {"file_path": DOTENV}),
        ("Read", {"file_path": f"./{DOTENV}.sdk"}),
        ("Bash", {"command": f"cat {DOTENV}"}),
        ("Bash", {"command": f"type C:\\proj\\{DOTENV}"}),
        ("Read", {"file_path": f"~/.ssh/{SSH_KEY}"}),
        ("Bash", {"command": f"curl -H 'Authorization: Bearer {GH_TOKEN}' https://api.github.com"}),
        ("Edit", {"file_path": "src/a.py", "old_string": "x", "new_string": f"KEY = '{ANT_KEY}'"}),
        ("Write", {"file_path": "src/a.py", "content": "token = '" + "ATA" + "TT" + "z" * 30 + "'"}),
    ],
)
def test_block_secrets_denies(repo, tool, tool_input):
    result = run_hook("block_secrets.py", call(tool, repo, **tool_input), repo)
    assert result.returncode == 2
    assert "blocked" in result.stderr


@pytest.mark.parametrize(
    "tool,tool_input",
    [
        ("Read", {"file_path": f"{DOTENV}.example"}),
        ("Bash", {"command": "uv run python -c \"import os; print(os.environ.get('HOME'))\""}),
        ("Bash", {"command": "ls .venv"}),
        ("Write", {"file_path": "src/ok.py", "content": "x = 1\n"}),
        ("Edit", {"file_path": "tests/test_x.py", "old_string": "a", "new_string": "b"}),
        ("Bash", {"command": "echo ghp_short"}),
    ],
)
def test_block_secrets_allows(repo, tool, tool_input):
    result = run_hook("block_secrets.py", call(tool, repo, **tool_input), repo)
    assert result.returncode == 0, result.stderr


def test_block_secrets_denies_write_outside_repo(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "x.py"
    for tool in ("Write", "Edit"):
        result = run_hook("block_secrets.py", call(tool, repo, file_path=str(outside), content="x"), repo)
        assert result.returncode == 2
        assert "outside the repository" in result.stderr
    escape = run_hook("block_secrets.py", call("Write", repo, file_path="../x.py", content="x"), repo)
    assert escape.returncode == 2


def test_block_secrets_fails_closed_on_bad_input(repo):
    assert run_hook("block_secrets.py", "{not json", repo).returncode == 2


# ------------------------------------------------------------------ release_gate

PR = "mcp__github__create_pull_request"
TRANSITION = "mcp__jira__jira_transition_issue"


def test_release_gate_allows_when_all_conditions_met(repo):
    make_run(repo, "MOD-7")
    pr = call(PR, repo, head="cr/MOD-7", base="main", title="feat(cbl0042): fee waiver [MOD-7]")
    assert run_hook("release_gate.py", pr, repo).returncode == 0
    jira = call(TRANSITION, repo, issue_key="MOD-7", transition_id="31")
    assert run_hook("release_gate.py", jira, repo).returncode == 0


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"verdict": "fail"}, "verdict='fail'"),
        ({"verdict": None}, "04-review.json is missing"),
        ({"ready": False}, "ready=False"),
        ({"docx": False}, "design/MOD-7-design.docx does not exist"),
    ],
)
def test_release_gate_denies_when_a_condition_fails(repo, kwargs, expected):
    make_run(repo, "MOD-7", **kwargs)
    for payload in (
        call(PR, repo, head="cr/MOD-7", base="main", title="feat: x [MOD-7]"),
        call(TRANSITION, repo, issue_key="MOD-7", transition_id="31"),
    ):
        result = run_hook("release_gate.py", payload, repo)
        assert result.returncode == 2
        assert expected in result.stderr


def test_release_gate_key_from_title_only(repo):
    make_run(repo, "MOD-7", verdict="fail")
    result = run_hook("release_gate.py", call(PR, repo, head="feature", title="fix [MOD-7]"), repo)
    assert result.returncode == 2
    assert "MOD-7" in result.stderr


def test_release_gate_denies_without_key_or_with_conflicting_keys(repo):
    make_run(repo, "MOD-7")
    make_run(repo, "MOD-8")
    none = run_hook("release_gate.py", call(PR, repo, head="feature", title="no key"), repo)
    assert none.returncode == 2 and "no CR key" in none.stderr
    both = run_hook("release_gate.py", call(PR, repo, head="cr/MOD-7", title="x [MOD-8]"), repo)
    assert both.returncode == 2 and "conflicting" in both.stderr


def test_release_gate_falls_back_to_git_branch(repo):
    make_run(repo, "MOD-7")
    subprocess.run(["git", "init", "-q", "-b", "cr/MOD-7", str(repo)], check=True)
    result = run_hook("release_gate.py", call(TRANSITION, repo, transition_id="31"), repo)
    assert result.returncode == 0, result.stderr


# ------------------------------------------------------------------ push_guard


def git_repo(repo: Path, branch: str) -> Path:
    subprocess.run(["git", "init", "-q", "-b", branch, str(repo)], check=True)
    return repo


def push_hook(repo: Path, command: str) -> subprocess.CompletedProcess:
    return run_hook("push_guard.py", call("Bash", repo, command=command), repo)


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git push origin HEAD:main",
        "git push origin +main",
        "git push origin refs/heads/main",
        "git push origin cr/MOD-9:refs/heads/main",
        "git push origin :main",
        "git push --set-upstream origin main",
        "git push -u origin main",
        "git push --force-with-lease origin main",
        "git push --all origin",
        "git -C . push origin main",
        "git -c push.default=current push origin main",
        "cd src && git push origin main",
        "git status; git push origin main",
        "GIT_TRACE=1 git push origin main",
        "bash -c 'git push origin main'",
        "git.exe push origin main",
    ],
)
def test_push_guard_denies_push_to_main(repo, command):
    git_repo(repo, "cr/MOD-9")
    result = push_hook(repo, command)
    assert result.returncode == 2, command
    assert "push_guard" in result.stderr


@pytest.mark.parametrize("command", ["git push", "git push origin", "git push origin HEAD", "git push -u origin @"])
def test_push_guard_denies_implicit_push_on_main(repo, command):
    git_repo(repo, "main")
    result = push_hook(repo, command)
    assert result.returncode == 2, command
    assert "main" in result.stderr


def test_push_guard_denies_implicit_push_when_branch_unknown(repo):
    result = push_hook(repo, "git push")  # tmp_path is not a git repo
    assert result.returncode == 2
    assert "could not be determined" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "gh pr merge 1",
        "gh pr merge 1 --squash --delete-branch",
        "gh api -X PUT repos/mirrellk/modernizeops/pulls/1/merge",
        "gh api /repos/o/r/pulls/12/merge -X PUT -f merge_method=squash",
        "uv run pytest -q && gh pr merge 3",
    ],
)
def test_push_guard_denies_pr_merge(repo, command):
    result = push_hook(repo, command)
    assert result.returncode == 2, command
    assert "merge" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "git push origin cr/MOD-9",
        "git push -u origin cr/MOD-9",
        "git push origin HEAD:cr/MOD-9",
        "git push origin main:cr/MOD-9",
        "git push",
        "git push origin HEAD",
        "git status",
        "echo 'git push origin main'",
        "gh pr view 1",
        "gh pr create --base main --head cr/MOD-9",
        "gh api repos/o/r/pulls/1",
        "uv run pytest -q",
    ],
)
def test_push_guard_allows(repo, command):
    git_repo(repo, "cr/MOD-9")
    result = push_hook(repo, command)
    assert result.returncode == 0, f"{command}: {result.stderr}"


def test_push_guard_fails_closed_on_bad_input(repo):
    assert run_hook("push_guard.py", "{not json", repo).returncode == 2
    assert push_hook(repo, "git push origin 'main").returncode == 2  # unbalanced quote


def ps_hook(repo: Path, command: str) -> subprocess.CompletedProcess:
    return run_hook("push_guard.py", call("PowerShell", repo, command=command), repo)


def encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


@pytest.mark.parametrize(
    "command",
    [
        "git push origin HEAD:main",
        "git.exe push origin +main",
        "& git push origin main",
        "&git push origin refs/heads/main",
        "& 'C:\\Program Files\\Git\\cmd\\git.exe' push origin main",
        '& "C:\\Program Files\\Git\\cmd\\git.exe" push -u origin main',
        "Set-Location src; git push origin main",
        "git status; git push origin main",
        "$env:GIT_TRACE='1'; git push origin main",
        "git fetch && git push origin main",
        "& { git push origin main }",
        "git PUSH origin main",
        "Start-Process git -ArgumentList 'push origin HEAD:main' -NoNewWindow -Wait",
        "Start-Process -FilePath git.exe -ArgumentList 'push','origin','main'",
        "Start-Process -FilePath git -ArgumentList push, origin, main -Wait",
        "start-process -file git -arg 'push --set-upstream origin main'",
        "Start-Process git -ArgumentList:'push origin main'",
        "saps git 'push origin main'",
        "Start-Process -WorkingDirectory src -FilePath git -ArgumentList 'push origin main'",
        "Invoke-Expression 'git push origin main'",
        'iex "git push origin main"',
        'powershell -NoProfile -Command "git push origin main"',
        "pwsh -c 'git push origin main'",
        "powershell -EncodedCommand " + encoded("git push origin main"),
        "cmd /c git push origin main",
        "gh pr merge 1 --squash",
        "Start-Process gh -ArgumentList 'pr merge 1'",
        "gh api -X PUT repos/o/r/pulls/1/merge",
    ],
)
def test_push_guard_powershell_denies(repo, command):
    git_repo(repo, "cr/MOD-9")
    result = ps_hook(repo, command)
    assert result.returncode == 2, command
    assert "push_guard" in result.stderr


@pytest.mark.parametrize("command", ["git push", "& git push", "Start-Process git -ArgumentList push -Wait"])
def test_push_guard_powershell_denies_implicit_push_on_main(repo, command):
    git_repo(repo, "main")
    result = ps_hook(repo, command)
    assert result.returncode == 2, command
    assert "main" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "git push origin cr/MOD-9",
        "& git push -u origin cr/MOD-9",
        "& 'C:\\Program Files\\Git\\cmd\\git.exe' push origin HEAD:cr/MOD-9",
        "git push",
        "Start-Process git -ArgumentList 'push origin cr/MOD-9' -Wait",
        'powershell -Command "git push origin cr/MOD-9"',
        "Write-Output 'git push origin main'",
        "git status; uv run pytest -q",
        "Get-ChildItem C:\\Users",
        "Start-Process notepad",
        "gh pr view 1",
    ],
)
def test_push_guard_powershell_allows(repo, command):
    git_repo(repo, "cr/MOD-9")
    result = ps_hook(repo, command)
    assert result.returncode == 0, f"{command}: {result.stderr}"


def test_push_guard_checks_powershell_called_from_bash(repo):
    git_repo(repo, "cr/MOD-9")
    assert push_hook(repo, "powershell.exe -Command 'git push origin main'").returncode == 2
    assert push_hook(repo, "pwsh -c 'git push origin cr/MOD-9'").returncode == 0


def test_push_guard_powershell_fails_closed(repo):
    assert ps_hook(repo, "git push origin 'main").returncode == 2  # unbalanced quote
    assert ps_hook(repo, "powershell -EncodedCommand not-base64!").returncode == 2


# ------------------------------------------------------------------ agent_paths

QA = "qa-reviewer"
ENG = "modernization-engineer"


@pytest.fixture
def runs(repo):
    other = make_run(repo, "MOD-8")
    active = make_run(repo, "MOD-7")
    touch_status(active)
    for run in (active, other):
        (run / "02-impact.md").write_text("impact\n", encoding="utf-8")
        (run / "03-build.md").write_text("narrative\n", encoding="utf-8")
    (repo / "src" / "fees.py").write_text("x = 1\n", encoding="utf-8")
    return repo


def agent_hook(repo, tool, agent, **tool_input):
    return run_hook("agent_paths.py", call(tool, repo, agent, **tool_input), repo)


@pytest.mark.parametrize(
    "tool,tool_input",
    [
        ("Read", {"file_path": "runs/MOD-7/03-build.md"}),
        ("Read", {"file_path": "runs/MOD-8/03-build.md"}),
        ("Read", {"file_path": "runs\\MOD-7\\03-BUILD.MD"}),
        ("Grep", {"pattern": "Decimal", "path": "runs/MOD-7"}),
        ("Grep", {"pattern": "Decimal"}),
        ("Grep", {"pattern": "Decimal", "glob": "*.md"}),
        ("Glob", {"pattern": "runs/**/03-build.md"}),
        ("Bash", {"command": "cat runs/MOD-7/03-build.md"}),
        ("Bash", {"command": "Get-Content runs\\MOD-7\\03-build.md"}),
        ("Bash", {"command": "cat runs/MOD-7/*"}),
        ("Bash", {"command": "grep -rn Decimal runs"}),
        ("Bash", {"command": "rg Decimal"}),
    ],
)
def test_qa_cannot_read_build_note(runs, tool, tool_input):
    result = agent_hook(runs, tool, QA, **tool_input)
    assert result.returncode == 2
    assert "03-build.md" in result.stderr


@pytest.mark.parametrize(
    "tool,tool_input",
    [
        ("Read", {"file_path": "runs/MOD-7/02-impact.md"}),
        ("Read", {"file_path": "src/fees.py"}),
        ("Grep", {"pattern": "Decimal", "path": "src"}),
        ("Grep", {"pattern": "Decimal", "type": "py"}),
        ("Grep", {"pattern": "Decimal", "glob": "*.py"}),
        ("Glob", {"pattern": "src/**/*.py"}),
        ("Bash", {"command": "uv run pytest -q 2>&1"}),
        ("Bash", {"command": "git diff main --name-only"}),
        ("Bash", {"command": "rg Decimal src tests"}),
        ("Write", {"file_path": "runs/MOD-7/04-review.json", "content": "{}"}),
    ],
)
def test_qa_allowed_calls(runs, tool, tool_input):
    result = agent_hook(runs, tool, QA, **tool_input)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "tool,tool_input",
    [
        ("Write", {"file_path": "runs/MOD-8/04-review.json", "content": "{}"}),
        ("Write", {"file_path": "runs/MOD-7/02-impact.md", "content": "x"}),
        ("Edit", {"file_path": "src/fees.py", "old_string": "1", "new_string": "2"}),
        ("Write", {"file_path": "tests/test_new.py", "content": "x"}),
        ("Bash", {"command": "echo '{}' > runs/MOD-7/STATUS.log"}),
        ("Bash", {"command": "rm src/fees.py"}),
    ],
)
def test_qa_writes_only_its_review(runs, tool, tool_input):
    result = agent_hook(runs, tool, QA, **tool_input)
    assert result.returncode == 2
    assert "runs/MOD-7/04-review.json" in result.stderr


@pytest.mark.parametrize(
    "tool,tool_input",
    [
        ("Write", {"file_path": "src/keystone/fees.py", "content": "x = 1\n"}),
        ("Edit", {"file_path": "tests/test_fees.py", "old_string": "a", "new_string": "b"}),
        ("Write", {"file_path": "runs/MOD-7/03-build.md", "content": "notes"}),
        ("Bash", {"command": "uv run pytest -q 2>&1 | tail -5"}),
        ("Bash", {"command": "echo x > src/gen.py && mkdir -p tests/fixtures"}),
        ("Bash", {"command": "cp corpus/legacy/a.cbl tests/fixtures/a.cbl"}),
        ("Read", {"file_path": "runs/MOD-7/03-build.md"}),
    ],
)
def test_engineer_allowed_writes(runs, tool, tool_input):
    result = agent_hook(runs, tool, ENG, **tool_input)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "tool,tool_input",
    [
        ("Write", {"file_path": "runs/MOD-8/03-build.md", "content": "x"}),
        ("Write", {"file_path": "runs/MOD-7/04-review.json", "content": "{}"}),
        ("Edit", {"file_path": "runs/MOD-7/01-brief.json", "old_string": "a", "new_string": "b"}),
        ("Write", {"file_path": "README.md", "content": "x"}),
        ("Write", {"file_path": "src", "content": "x"}),
        ("Edit", {"file_path": ".claude/settings.json", "old_string": "a", "new_string": "b"}),
        ("Bash", {"command": "echo pass > runs/MOD-7/04-review.json"}),
        ("Bash", {"command": "mv src/fees.py design/fees.py"}),
        ("Bash", {"command": "rm -rf corpus"}),
        ("Bash", {"command": "Set-Content -Path pyproject.toml -Value x"}),
        ("Bash", {"command": "sed -i 's/a/b/' CLAUDE.md"}),
    ],
)
def test_engineer_writes_restricted(runs, tool, tool_input):
    result = agent_hook(runs, tool, ENG, **tool_input)
    assert result.returncode == 2
    assert "write scope" in result.stderr


def test_engineer_without_active_run_cannot_write_runs(repo):
    (repo / "runs" / "MOD-7").mkdir(parents=True)
    result = agent_hook(repo, "Write", ENG, file_path="runs/MOD-7/03-build.md", content="x")
    assert result.returncode == 2
    assert "no active CR" in result.stderr
    assert agent_hook(repo, "Write", ENG, file_path="src/a.py", content="x").returncode == 0


def test_other_agents_unrestricted(runs):
    result = agent_hook(runs, "Write", "legacy-analyst", file_path="runs/MOD-7/02-impact.md", content="x")
    assert result.returncode == 0
    assert not (runs / "logs").exists()


def test_unidentified_agent_allowed_and_logged(runs):
    result = agent_hook(runs, "Read", None, file_path="runs/MOD-7/03-build.md")
    assert result.returncode == 0
    [log] = (runs / "logs").glob("agent-paths-*.jsonl")
    record = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert record["decision"] == "allow"
    assert record["reason"] == "agent not identified"
    assert record["tool_name"] == "Read"


def test_plugin_scoped_agent_name_is_recognised(runs):
    result = agent_hook(runs, "Read", "modernizeops:qa-reviewer", file_path="runs/MOD-7/03-build.md")
    assert result.returncode == 2


# ------------------------------------------------------------------ post_edit_lint


def test_post_edit_lint_fixes_and_reports_remaining(repo):
    target = repo / "src" / "bad.py"
    target.write_text("import os\n\n\ndef f():\n    return undefined_name\n", encoding="utf-8")
    result = run_hook("post_edit_lint.py", call("Write", repo, file_path=str(target), content=""), repo)
    assert result.returncode == 2
    assert "F821" in result.stderr
    assert "import os" not in target.read_text(encoding="utf-8")  # F401 auto-fixed


def test_post_edit_lint_clean_and_non_python(repo):
    clean = repo / "src" / "ok.py"
    clean.write_text("X = 1\n", encoding="utf-8")
    assert run_hook("post_edit_lint.py", call("Edit", repo, file_path=str(clean)), repo).returncode == 0
    notes = repo / "notes.md"
    notes.write_text("import os\n", encoding="utf-8")
    assert run_hook("post_edit_lint.py", call("Write", repo, file_path=str(notes)), repo).returncode == 0


# ------------------------------------------------------------------ audit_log


def test_audit_log_writes_redacted_line(repo):
    payload = {
        "session_id": "s-1",
        "agent_type": "qa-reviewer",
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {
            "command": f"echo {GH_TOKEN}",
            "api_token": "abc",
            "nested": {"Password": "hunter2", "path": "src/a.py"},
            "client_secret": "s",
            "issue_key": "MOD-7",
            "content": "y" * 5000,
        },
        "tool_response": {"success": True},
    }
    result = run_hook("audit_log.py", payload, repo)
    assert result.returncode == 0, result.stderr
    [log] = (repo / "logs").glob("audit-*.jsonl")
    record = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert set(record) == {"time", "session_id", "agent", "tool_name", "tool_input", "success"}
    assert record["session_id"] == "s-1"
    assert record["agent"] == "qa-reviewer"
    assert record["success"] is True
    ti = record["tool_input"]
    assert ti["api_token"] == ti["client_secret"] == ti["issue_key"] == "***"
    assert ti["nested"] == {"Password": "***", "path": "src/a.py"}
    assert GH_TOKEN not in ti["command"]
    assert len(ti["content"]) < 1100
    assert GH_TOKEN not in log.read_text(encoding="utf-8")


def test_audit_log_records_failure_and_appends(repo):
    for response in ({"success": False}, {"is_error": True}, "plain text output"):
        payload = {"session_id": "s", "tool_name": "Read", "tool_input": {}, "tool_response": response}
        assert run_hook("audit_log.py", payload, repo).returncode == 0
    [log] = (repo / "logs").glob("audit-*.jsonl")
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [r["success"] for r in records] == [False, False, True]
    assert records[0]["agent"] is None


def test_audit_log_never_blocks(repo):
    assert run_hook("audit_log.py", "{broken", repo).returncode == 0


# ------------------------------------------------------------------ session_context


def test_session_context_prints_last_status(repo):
    for key, lines in {
        "MOD-10": ["2026-11-12T14:00:00Z | intake | ok"],
        "MOD-3": [
            "2026-11-12T14:18:46Z | intake | ok (brief valid, ready=false)",
            "2026-11-12T14:18:50Z | readiness-gate | BLOCKED-NEEDS-INFO (5 questions)",
            "",
        ],
    }.items():
        run = repo / "runs" / key
        run.mkdir(parents=True)
        (run / "STATUS.log").write_text("\n".join(lines), encoding="utf-8")
    result = run_hook("session_context.py", {"hook_event_name": "SessionStart"}, repo)
    assert result.returncode == 0
    out = result.stdout.splitlines()
    assert out[1] == "- MOD-3: readiness-gate -> BLOCKED-NEEDS-INFO (5 questions) (2026-11-12T14:18:50Z)"
    assert out[2] == "- MOD-10: intake -> ok (2026-11-12T14:00:00Z)"


def test_session_context_without_runs(repo):
    result = run_hook("session_context.py", {}, repo)
    assert result.returncode == 0
    assert "none yet" in result.stdout
