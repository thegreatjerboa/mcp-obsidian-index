# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP server providing semantic search over Obsidian vault(s). Exposes notes as resources and a `search-notes` tool via the Model Context Protocol for integration with Claude Desktop and other MCP clients.

## Development Commands

```bash
uv sync                    # Install/sync dependencies
uv run ruff check .        # Lint
uv run ruff format .       # Format
uv run obsidian-index mcp --vault <PATH> --database <DB_PATH> --reindex --watch  # Run server
```

**Debugging with MCP Inspector:**
```bash
npx @modelcontextprotocol/inspector uv --directory . run obsidian-index mcp --vault <PATH> --database <DB_PATH>
```

## Architecture

The system uses a **background worker process** to handle all DuckDB operations (DuckDB lacks async/concurrency support).

```
MCP Server (mcp_server.py)
    │ stdio communication with MCP clients
    ▼
BaseController (background_worker.py)
    │ async request/response via queues + correlation IDs
    ▼
Worker Process (index/worker.py)
    ├── Indexer: encodes documents → embeddings
    ├── Searcher: queries embeddings
    ├── Database: DuckDB vector storage
    └── DirectoryWatcher: monitors .md file changes
```

**Key flow:**
1. File watcher detects markdown changes → enqueues `IndexMessage`
2. Indexer batches files, generates embeddings via Sentence Transformers
3. Embeddings stored in DuckDB with vault name, path, modification time
4. Search queries encoded with same model, DuckDB performs vector similarity

## Key Implementation Details

- **Embedding model:** `sentence-transformers/paraphrase-MiniLM-L6-v2` (384 dimensions)
- **Device:** Auto-detected (CUDA → MPS → CPU) in encoder.py
- **Resource URIs:** `obsidian://<VAULT_NAME>/<NOTE_PATH>`
- **DuckDB limitation:** Array updates not supported, so embeddings are deleted and re-inserted

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OBSIDIAN_INDEX_POLLING` | `false` | Set to `1` or `true` to use PollingObserver instead of inotify. Required for Docker on Windows. |

## Docker

Build and run with Docker:

```bash
docker build -t obsidian-index:local .
docker run -i --rm \
  -v "C:/path/to/vault:/vault:ro" \
  -v "C:/path/to/data:/data" \
  obsidian-index:local
```

The Dockerfile sets `OBSIDIAN_INDEX_POLLING=true` by default for compatibility with Docker volume mounts.
