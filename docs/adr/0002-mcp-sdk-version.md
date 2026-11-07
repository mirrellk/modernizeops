# ADR 0002: MCP Python SDK version for the keystone-kb server

- **Status:** Accepted
- **Date:** 2026-11-06
- **Deciders:** ModernizeOps maintainers

## Context
The keystone-kb server (`mcp_servers/kb_server/server.py`) needs an MCP Python SDK. The 1.x line, with its `FastMCP` class, is the superseded major version. 2.x replaces it with `MCPServer`.

## Decision
Build on mcp 2.x `MCPServer`, not 1.x `FastMCP`. The tools, resources and prompt it exposes are the same either way: the `search_kb`, `get_source` and `list_programs` tools, the `kb://standards/{name}`, `kb://copybooks/{name}` and `kb://inventory` resources, the `impact_analysis` prompt, and the JSON error contract.

## Consequences
We stay on the maintained SDK line. Examples and code written for 1.x `FastMCP` need porting to 2.x before they can be reused here.
