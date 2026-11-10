# MCP Server Inventory — ModernizeOps

Approved MCP servers for this project. No server may be added to .mcp.json without a row here.

| Server | Publisher | Official / community | Transport | Auth | Tools enabled | Data it can reach | Owner | Reviewed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| kb (keystone-kb) | Internal (this repo) | Internal | Local, stdio | None | search_kb, get_source, list_programs (3) | corpus/ only (local) | Mirrell Knabe | 2026-11-09 |
| github | GitHub | Official | Remote, Streamable HTTP | Fine-grained PAT, Bearer header | Toolsets: repos, pull_requests (30 tools) | mirrellk/modernizeops only (PAT scope) | Mirrell Knabe | 2026-11-09 |
| jira (mcp-atlassian) | sooperset (community) | Community | Local, stdio (uv tool, pinned v0.24.1) | Atlassian API token | jira_get_issue, jira_search, jira_add_comment, jira_transition_issue, jira_get_transitions (5) | Project MOD on mirrellk.atlassian.net | Mirrell Knabe | 2026-11-09 |
| context7 | Upstash | Official | Remote, Streamable HTTP | Optional API key (none set) | Library documentation lookup (2 tools) | Public docs only; receives query text | Mirrell Knabe | 2026-11-09 |
| office (keystone-office) | Internal (this repo) | Internal | Local, stdio | None | create_design_doc, append_impact_rows, read_impact_matrix (3) | design/ and templates/ (local) | Mirrell Knabe | 2026-11-09 |

## Rules

- Community servers are installed with `uv tool install`, pinned to a version, and re-reviewed on every upgrade. No runtime downloads (`uvx`) at server start.
- Remote servers never receive secrets or client data in queries.
- Tokens are scoped to the minimum (one repo, one project) and stored only in .env.

## Change log

- 2026-11-09: jira switched from `uvx mcp-atlassian` to a pinned `uv tool` install; HTTPS inspection on the workstation blocked uvx's runtime fetch from PyPI. `UV_NATIVE_TLS=true` set at user level.
- 2026-11-10: renamed user-level `UV_NATIVE_TLS=true` to `UV_SYSTEM_CERTS=true` (uv deprecated the old name); same behavior, uv trusts the Windows certificate store.
