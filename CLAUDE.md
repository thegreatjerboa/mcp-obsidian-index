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

**Benchmarking models:**
```bash
uv run python scripts/benchmark.py --vault /path/to/vault --sample 50
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

- **Embedding model:** Configurable (default: `paraphrase-MiniLM-L6-v2`, 384 dimensions)
- **Device:** Auto-detected (CUDA → MPS → CPU) in encoder.py
- **Resource URIs:** `obsidian://<VAULT_NAME>/<NOTE_PATH>`
- **DuckDB limitation:** Array updates not supported, so embeddings are deleted and re-inserted
- **Content hashing:** Files are hashed (SHA-256) and only reindexed when content changes, reducing unnecessary embedding computations

## Supported Embedding Models

| Model | Dimensions | Max Tokens | Notes |
|-------|------------|------------|-------|
| `paraphrase-MiniLM-L6-v2` | 384 | 256 | Default, fast and lightweight |
| `all-MiniLM-L6-v2` | 384 | 256 | Popular general-purpose |
| `bge-small-en-v1.5` | 384 | 512 | Better for longer chunks |
| `all-mpnet-base-v2` | 768 | 384 | Higher quality embeddings |
| `nomic-embed-text-v1` | 768 | 8192 | Best for long documents |

**Changing models:** When you change the configured model, the database will automatically detect the mismatch and clear the index, triggering a full reindex with the new model.

## Incremental Indexing

The indexer uses content hashing to avoid unnecessary reindexing:
- Each file's content is hashed (SHA-256) and stored in the database
- On reindex, files are only re-embedded if their content hash has changed
- This makes `--reindex` safe to run frequently without performance penalty
- Model changes trigger a full reindex (hashes are preserved but embeddings are regenerated)

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OBSIDIAN_INDEX_POLLING` | `false` | Set to `1` or `true` to use PollingObserver instead of inotify. Required for Docker on Windows. |
| `OBSIDIAN_INDEX_MODEL` | `paraphrase-MiniLM-L6-v2` | Embedding model to use. See supported models above. |

## CLI Options

```
obsidian-index mcp [OPTIONS]

Options:
  -d, --database PATH    Path to the database (required)
  -v, --vault PATH       Vault to index (required, can be specified multiple times)
  --reindex              Reindex all notes
  --watch                Watch for changes
  -m, --model MODEL      Embedding model to use (overrides OBSIDIAN_INDEX_MODEL env var)
```

## Docker

Build and run with Docker:

```bash
docker build -t obsidian-index:local .
docker run -i --rm \
  -v "C:/path/to/vault:/vault:ro" \
  -v "C:/path/to/data:/data" \
  obsidian-index:local
```

With a different model:
```bash
docker run -i --rm \
  -v "C:/path/to/vault:/vault:ro" \
  -v "C:/path/to/data:/data" \
  -e OBSIDIAN_INDEX_MODEL=all-mpnet-base-v2 \
  obsidian-index:local
```

The Dockerfile sets `OBSIDIAN_INDEX_POLLING=true` and `OBSIDIAN_INDEX_MODEL=paraphrase-MiniLM-L6-v2` by default.
