# Phase 10: enforcement TODO

The agent boundaries in `.claude/agents/` are currently prompt instructions only: `Write` can write
any path and `Bash` can run any command. Phase 10 turns these rules into `PreToolUse` hooks that
block the call regardless of what the agent decides.

| # | Agent | Rule | Tools to intercept | Block when |
|---|---|---|---|---|
| 1 | qa-reviewer | Must not read the author's narrative | Read, Grep, Glob, Bash | Target path matches `runs/*/03-build.md` (including Bash commands such as `cat`, `type`, `Get-Content` that reference it) |
| 2 | modernization-engineer | Writes limited to code, tests and its build note | Write, Edit, Bash (redirects, `mv`, `cp`, `rm`) | Target path is outside `src/`, `tests/` and `runs/<CR-KEY>/03-build.md` |
| 3 | qa-reviewer | Writes limited to its review | Write, Bash (redirects, `mv`, `cp`, `rm`) | Target path is anything other than `runs/<CR-KEY>/04-review.json` |

## Open points for Phase 10

- **Identifying the agent:** the hook has to know which subagent made the call. Decide how
  (hook input fields, or hooks declared in each agent's frontmatter).
- **Identifying the CR key:** `<CR-KEY>` must come from the active run, not from the agent, so that
  an agent can't write to another CR's folder.
- **Bash coverage:** path checks on Bash are best-effort. Decide whether to parse commands or to
  restrict Bash to an allow-list (`uv run pytest`, `uv run ruff`, `git diff`) for these agents.
