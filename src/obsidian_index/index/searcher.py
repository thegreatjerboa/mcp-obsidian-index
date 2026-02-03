from collections.abc import Sequence
from pathlib import Path

from obsidian_index.index.database_sqlite import Database
from obsidian_index.index.encoder import Encoder
from obsidian_index.index.messages import SearchResult
from obsidian_index.logger import logging

logger = logging.getLogger(__name__)

MAX_EXCERPT_LENGTH = 500  # chars for excerpt body


def extract_frontmatter(content: str) -> str:
    """Extract YAML frontmatter from markdown content."""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            return content[3:end].strip()
    return ""


def extract_outline(content: str) -> list[str]:
    """Extract headings from markdown content."""
    headings = []
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.append(stripped)
    return headings


def extract_excerpt(content: str, max_length: int = MAX_EXCERPT_LENGTH) -> str:
    """Extract a truncated excerpt from markdown content.

    Skips frontmatter if present.
    """
    text = content

    # Skip frontmatter
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3 :].lstrip()

    if len(text) <= max_length:
        return text

    # Truncate at word boundary
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")
    if last_space > max_length // 2:
        truncated = truncated[:last_space]

    return truncated + "..."


class Searcher:
    database: Database
    vaults: dict[str, Path]
    encoder: Encoder

    def __init__(
        self,
        database: Database,
        vaults: dict[str, Path],
        encoder: Encoder,
    ):
        self.database = database
        self.vaults = vaults
        self.encoder = encoder

    def search(self, query: str, top_k: int = 8) -> Sequence[SearchResult]:
        """
        Search for notes that match a query.

        Returns SearchResult objects with metadata for each result.
        """
        query_emb = self.encoder.encode_query(query)

        db_results = self.database.search(query_emb, top_k=top_k)

        results = []
        for vault_name, rel_path, distance in db_results:
            full_path = self.vaults[vault_name] / rel_path

            # Read file content
            try:
                if not full_path.exists():
                    logger.warning("Stale index entry, skipping: %s", full_path)
                    continue
                content = full_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("Failed to read file %s: %s", full_path, e)
                continue

            # Extract metadata
            frontmatter = extract_frontmatter(content)
            outline = extract_outline(content)
            excerpt = extract_excerpt(content)

            results.append(
                SearchResult(
                    vault_name=vault_name,
                    path=full_path,
                    score=distance,
                    frontmatter=frontmatter,
                    outline=outline,
                    excerpt=excerpt,
                )
            )

        return results
