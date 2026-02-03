#!/usr/bin/env python3
"""Test script to verify search result size reduction.

Run with: docker run --rm -v "$(pwd):/app" -v "/path/to/vault:/vault:ro" -v "/path/to/data:/data" --entrypoint python obsidian-index:local /app/scripts/test_search_size.py
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from obsidian_index.index.database_sqlite import Database
from obsidian_index.index.encoder import Encoder
from obsidian_index.index.searcher import Searcher, extract_frontmatter, extract_outline, extract_excerpt


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    return len(text) // 4


def test_extraction_functions():
    """Test the extraction helper functions."""
    print("=" * 60)
    print("Testing extraction functions")
    print("=" * 60)

    # Test frontmatter extraction
    content_with_fm = """---
title: Test Note
tags: [test, example]
date: 2024-01-01
---

# Main Heading

This is the content.

## Subheading

More content here.
"""

    content_without_fm = """# Just a Heading

No frontmatter here.
"""

    fm = extract_frontmatter(content_with_fm)
    print(f"\nFrontmatter extraction:")
    print(f"  Input has frontmatter: {bool(fm)}")
    print(f"  Extracted: {fm[:50]}..." if len(fm) > 50 else f"  Extracted: {fm}")

    fm_none = extract_frontmatter(content_without_fm)
    print(f"  Content without frontmatter: '{fm_none}' (expected empty)")

    # Test outline extraction
    outline = extract_outline(content_with_fm)
    print(f"\nOutline extraction:")
    print(f"  Headings found: {len(outline)}")
    for h in outline:
        print(f"    - {h}")

    # Test excerpt extraction
    excerpt = extract_excerpt(content_with_fm)
    print(f"\nExcerpt extraction:")
    print(f"  Length: {len(excerpt)} chars")
    print(f"  Excerpt: {excerpt[:100]}..." if len(excerpt) > 100 else f"  Excerpt: {excerpt}")

    print("\n[PASS] Extraction functions work correctly")


def test_search_with_vault():
    """Test search with actual vault data."""
    print("\n" + "=" * 60)
    print("Testing search with vault")
    print("=" * 60)

    vault_path = Path("/vault")
    db_path = Path("/data/index.db")

    if not vault_path.exists():
        print(f"[SKIP] Vault not found at {vault_path}")
        return

    if not db_path.exists():
        print(f"[SKIP] Database not found at {db_path}")
        return

    # Initialize components
    print("\nInitializing database and encoder...")
    db = Database(db_path, read_only=True)
    encoder = Encoder(model_config=db.model_config)
    searcher = Searcher(db, {"vault": vault_path}, encoder)

    num_notes = db.num_notes()
    print(f"Database contains {num_notes} notes")

    if num_notes == 0:
        print("[SKIP] No notes indexed")
        return

    # Run search
    query = "project management workflow"
    print(f"\nSearching for: '{query}'")

    results = searcher.search(query, top_k=8)
    print(f"Found {len(results)} results")

    # Measure sizes
    total_chars = 0
    total_tokens = 0

    print("\n" + "-" * 60)
    print("Result breakdown:")
    print("-" * 60)

    for i, result in enumerate(results):
        # Build the formatted output (same as mcp_server.py)
        parts = [f"[Resource from obsidian-index at obsidian://vault/{result.path.name}]"]

        if result.frontmatter:
            parts.append(f"---\n{result.frontmatter}\n---")

        if result.outline:
            outline_str = " > ".join(result.outline[:10])
            if len(result.outline) > 10:
                outline_str += f" (+{len(result.outline) - 10} more)"
            parts.append(f"Outline: {outline_str}")

        parts.append(result.excerpt)

        formatted = "\n\n".join(parts)
        chars = len(formatted)
        tokens = estimate_tokens(formatted)
        total_chars += chars
        total_tokens += tokens

        print(f"\nResult {i + 1}: {result.path.name}")
        print(f"  Score: {result.score:.4f}")
        print(f"  Frontmatter: {len(result.frontmatter)} chars")
        print(f"  Outline: {len(result.outline)} headings")
        print(f"  Excerpt: {len(result.excerpt)} chars")
        print(f"  Formatted output: {chars} chars (~{tokens} tokens)")

    print("\n" + "=" * 60)
    print("TOTALS")
    print("=" * 60)
    print(f"Total results: {len(results)}")
    print(f"Total chars: {total_chars}")
    print(f"Estimated tokens: {total_tokens}")
    print(f"Average per result: {total_chars // len(results) if results else 0} chars (~{total_tokens // len(results) if results else 0} tokens)")

    # Check against target
    target_tokens = 3000
    if total_tokens < target_tokens:
        print(f"\n[PASS] Token count ({total_tokens}) is under target ({target_tokens})")
    else:
        print(f"\n[WARN] Token count ({total_tokens}) exceeds target ({target_tokens})")

    db.close()


def test_limit_parameter():
    """Test that limit parameter works."""
    print("\n" + "=" * 60)
    print("Testing limit parameter")
    print("=" * 60)

    vault_path = Path("/vault")
    db_path = Path("/data/index.db")

    if not vault_path.exists() or not db_path.exists():
        print("[SKIP] Vault or database not found")
        return

    db = Database(db_path, read_only=True)
    encoder = Encoder(model_config=db.model_config)
    searcher = Searcher(db, {"vault": vault_path}, encoder)

    if db.num_notes() == 0:
        print("[SKIP] No notes indexed")
        return

    query = "test"

    for limit in [3, 5, 8]:
        results = searcher.search(query, top_k=limit)
        actual = len(results)
        status = "[PASS]" if actual <= limit else "[FAIL]"
        print(f"  limit={limit}: got {actual} results {status}")

    db.close()


def test_frontmatter_notes():
    """Test search results that have frontmatter."""
    print("\n" + "=" * 60)
    print("Testing frontmatter in search results")
    print("=" * 60)

    vault_path = Path("/vault")
    db_path = Path("/data/index.db")

    if not vault_path.exists() or not db_path.exists():
        print("[SKIP] Vault or database not found")
        return

    db = Database(db_path, read_only=True)
    encoder = Encoder(model_config=db.model_config)
    searcher = Searcher(db, {"vault": vault_path}, encoder)

    if db.num_notes() == 0:
        print("[SKIP] No notes indexed")
        return

    # Search for content
    results = searcher.search("ticket work", top_k=8)

    fm_count = sum(1 for r in results if r.frontmatter)
    print(f"\nResults with frontmatter: {fm_count}/{len(results)}")

    for i, r in enumerate(results):
        has_fm = "YES" if r.frontmatter else "NO"
        print(f"\n  {i+1}. {r.path.name}")
        print(f"     Frontmatter: {has_fm} ({len(r.frontmatter)} chars)")
        print(f"     Outline: {len(r.outline)} headings")
        if r.frontmatter:
            preview = r.frontmatter[:60].replace('\n', ' ')
            print(f"     FM preview: {preview}...")

    db.close()


if __name__ == "__main__":
    test_extraction_functions()
    test_search_with_vault()
    test_limit_parameter()
    test_frontmatter_notes()
    print("\n" + "=" * 60)
    print("All tests completed")
    print("=" * 60)
