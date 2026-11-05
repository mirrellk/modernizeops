# ModernizeOps

Agentic pipeline that turns Jira change requests (project MOD) against Keystone Federal Bank's
COBOL batch estate into reviewed Python changes, design docs and pull requests.

## Stack

Python 3.12 + uv. Tests: `uv run pytest -q`. Lint: `uv run ruff check .`
RAG: Ollama nomic-embed-text + ChromaDB in .rag/. MCP servers in mcp_servers/.

## Rules

- Money is Decimal, never float. Follow the cobol-conventions skill for PIC mapping.
- Every pipeline step writes its output to runs/<CR-KEY>/; read inputs from there, not from memory.
- Never read or print .env or any secret.
- Never push to main. All changes go through a cr/<CR-KEY> branch and a pull request.
- If a requirement is ambiguous, stop and ask; do not guess business rules.
