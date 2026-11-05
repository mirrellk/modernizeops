# ModernizeOps

ModernizeOps is a toolkit for modernizing legacy systems with AI assistance.
It indexes legacy artifacts and engineering standards into a local hybrid RAG store (ChromaDB + BM25, embeddings via Ollama).
Custom MCP servers expose that knowledge base and Office document generation (Word/Excel) to Claude Code.
The `keystone` package holds the core logic, with JSON schemas, templates, and evals to keep outputs consistent and measurable.
Set up with `uv sync`, copy `.env.example` to `.env`, and run tests with `uv run pytest`.
