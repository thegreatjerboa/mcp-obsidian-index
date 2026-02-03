# Testing

Manual integration tests for validating the MCP server functionality.

## Prerequisites

- Docker image built: `obsidian-index:local`
- Obsidian vault mounted at `/vault`
- Database directory mounted at `/data`
- ObsiMCP server available for CRUD operations (optional, for full integration testing)

## Test Suite

### 1. Search Functionality

| Test | Command/Action | Expected Result |
|------|----------------|-----------------|
| Basic search | `search-notes` with query "test" | Returns relevant notes ranked by semantic similarity |
| Specific search | `search-notes` with detailed query | Returns notes matching semantic meaning, not just keywords |
| Limit parameter | `search-notes` with `limit: 3` | Returns exactly 3 results |
| Result format | Any search query | Each result contains: resource URI, frontmatter (if present), outline, excerpt |
| Full content fetch | Use `read_resource` with URI from search result | Returns full note content |

**Search Result Format:**

Each search result is a `TextContent` object containing:
- Resource URI: `obsidian://{vault_name}/{relative_path}` for fetching full content
- Frontmatter: Raw YAML if present (without `---` delimiters in the excerpt)
- Outline: Headings joined with ` > ` (max 10 headings shown)
- Excerpt: First 500 characters of content (after frontmatter)

### 2. Index Updates

| Test | Action | Expected Result |
|------|--------|-----------------|
| New file indexed | Create a note, then search for it | New note appears in search results |
| Deleted file removed | Delete a note, then search for it | Deleted note does NOT appear in results |
| Modified file reindexed | Modify content, search for new content | Updated content is searchable |

### 3. CRUD Integration (with ObsiMCP)

These tests validate the full workflow when used alongside ObsiMCP for CRUD operations.

| Test | Tools Used | Expected Result |
|------|------------|-----------------|
| Create note | `CrateANote` | Note file created |
| Write content | `WriteNoteByFullPath` | Content written (append/overwrite) |
| Read content | `ReadNoteByFullPath` | Content returned correctly |
| Get frontmatter | `GetNoteFrontmatter` | YAML frontmatter extracted |
| Get tags | `GetNoteTags` | Tags from frontmatter returned |
| Search new note | `search-notes` | Newly created note appears in results |
| Move note | `MoveOneNote` | Note moved, old path removed from index |
| Delete note | `DeleteNote` | Note deleted, removed from search index |

### 4. Error Handling

| Test | Action | Expected Result |
|------|--------|-----------------|
| Search empty vault | Search with no indexed files | Empty results, no error |
| Search non-existent content | Search for content that doesn't exist | Empty or low-relevance results |

## Test Execution Log

### 2026-02-02

**Environment:**
- Docker: `obsidian-index:local`
- Model: `nomic-embed-text-v1`
- Vault: WorkVault mounted at `/vault`

**Results:**

| Test | Status | Notes |
|------|--------|-------|
| Basic search | Pass | Returns semantically relevant results |
| Create note | Pass | `/vault/00-Inbox/MCP-Test-Note-2026-02-02.md` created |
| Write content | Pass | Frontmatter and markdown content written |
| Read content | Pass | Content returned correctly |
| Get frontmatter | Pass | `tags: [test, mcp-validation]` extracted |
| Get tags | Pass | `Tags: test, mcp-validation` returned |
| New note in search | Pass | Note appeared immediately in search results |
| Create folder | Pass | `/vault/00-Inbox/test-folder-2026-02-02` created |
| Move note | Pass | Note moved to new folder |
| Delete note | Pass | Note deleted successfully |
| Deleted note not in search | Pass | Deleted note no longer appears in search results |

**All tests passed.**

## Running Tests Manually

1. Start the MCP server via Claude Code or MCP Inspector
2. Execute each test using the MCP tools
3. Verify expected results
4. Document any failures with reproduction steps

## Automated Testing

Currently no automated test suite exists. Future improvements could include:

- Python pytest suite using MCP client library
- Docker Compose setup for isolated test environment
- CI/CD integration for regression testing
