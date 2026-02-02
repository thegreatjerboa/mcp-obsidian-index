from collections.abc import Sequence
from pathlib import Path
from textwrap import dedent

import duckdb
import torch

from obsidian_index.index.models import EmbeddingModelConfig, get_model_config
from obsidian_index.logger import logging

logger = logging.getLogger(__name__)

# Legacy column name from before model was configurable
LEGACY_COLUMN_NAME = "emb_minilm_l6_v2"
LEGACY_MODEL_NAME = "paraphrase-MiniLM-L6-v2"


class Database:
    ddb_connection: duckdb.DuckDBPyConnection
    read_only: bool
    model_config: EmbeddingModelConfig

    def __init__(
        self,
        database_path: Path,
        read_only: bool = False,
        model_config: EmbeddingModelConfig | None = None,
    ):
        if model_config is None:
            model_config = get_model_config()

        self.model_config = model_config
        self.ddb_connection = duckdb.connect(database_path, read_only=read_only)
        self.read_only = read_only

        if not self.read_only:
            self.initialize()

    def _table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        result = self.ddb_connection.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            (table_name,),
        ).fetchone()
        return result[0] > 0  # type: ignore

    def _column_exists(self, table_name: str, column_name: str) -> bool:
        """Check if a column exists in a table."""
        result = self.ddb_connection.execute(
            "SELECT COUNT(*) FROM information_schema.columns WHERE table_name = ? AND column_name = ?",
            (table_name, column_name),
        ).fetchone()
        return result[0] > 0  # type: ignore

    def _get_stored_model(self) -> str | None:
        """Get the model name stored in the metadata table."""
        if not self._table_exists("metadata"):
            return None
        result = self.ddb_connection.execute(
            "SELECT value FROM metadata WHERE key = 'model_name'"
        ).fetchone()
        return result[0] if result else None

    def _set_stored_model(self, model_name: str):
        """Store the model name in the metadata table."""
        self.ddb_connection.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('model_name', ?)",
            (model_name,),
        )

    def _migrate_legacy_database(self):
        """Migrate from legacy database schema (emb_minilm_l6_v2 column)."""
        logger.info("Migrating legacy database schema...")

        # Create metadata table
        self.ddb_connection.execute(
            dedent("""
            CREATE TABLE IF NOT EXISTS metadata (
                key STRING PRIMARY KEY,
                value STRING
            )
        """)
        )

        # Record the legacy model
        self._set_stored_model(LEGACY_MODEL_NAME)

        # Rename the legacy column to 'embedding'
        self.ddb_connection.execute(
            f"ALTER TABLE notes RENAME COLUMN {LEGACY_COLUMN_NAME} TO embedding"
        )

        logger.info("Legacy database migration complete")

    def _migrate_add_content_hash(self):
        """Add content_hash column to existing notes table."""
        if self._table_exists("notes") and not self._column_exists("notes", "content_hash"):
            logger.info("Adding content_hash column to notes table...")
            self.ddb_connection.execute("ALTER TABLE notes ADD COLUMN content_hash STRING")
            logger.info("content_hash column added")

    def _handle_model_change(self, stored_model: str):
        """Handle a change in embedding model by clearing and recreating the notes table."""
        logger.warning(
            "Model changed from '%s' to '%s', clearing index and reindexing...",
            stored_model,
            self.model_config.name,
        )

        # Drop the existing notes table
        self.ddb_connection.execute("DROP TABLE IF EXISTS notes")

        # Update stored model
        self._set_stored_model(self.model_config.name)

        # Create the notes table with new dimensions
        self._create_notes_table()

    def _create_notes_table(self):
        """Create the notes table with the current model's dimensions."""
        self.ddb_connection.execute(
            dedent(f"""
            CREATE TABLE IF NOT EXISTS notes (
                path STRING PRIMARY KEY,
                vault_name STRING,
                last_modified FLOAT,
                content_hash STRING,
                embedding FLOAT[{self.model_config.dimensions}]
            )
        """)
        )

    def initialize(self):
        """
        Perform any necessary initialization of the database.
        """
        # Check if this is a legacy database
        is_legacy = self._table_exists("notes") and self._column_exists("notes", LEGACY_COLUMN_NAME)

        if is_legacy:
            self._migrate_legacy_database()

        # Ensure metadata table exists
        self.ddb_connection.execute(
            dedent("""
            CREATE TABLE IF NOT EXISTS metadata (
                key STRING PRIMARY KEY,
                value STRING
            )
        """)
        )

        # Check if model has changed
        stored_model = self._get_stored_model()

        if stored_model is None:
            # Fresh database or just migrated
            self._set_stored_model(self.model_config.name)
            self._create_notes_table()
        elif stored_model != self.model_config.name:
            # Model changed - need to clear and reindex
            self._handle_model_change(stored_model)
        else:
            # Same model - just ensure table exists
            self._create_notes_table()

        # Migrate to add content_hash if missing
        self._migrate_add_content_hash()

    def num_notes(self) -> int:
        """
        Get the total number of notes in the database.
        """
        return self.ddb_connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0]  # type: ignore

    def get_most_recent_seen_timestamp(self, vault_name: str) -> float:
        """
        Get the most recent seen timestamp for a vault.
        """
        return self.ddb_connection.execute(
            "SELECT max(last_modified) FROM notes WHERE vault_name = ?", (vault_name,)
        ).fetchone()[0]  # type: ignore

    def delete_note(self, vault_name: str, path: Path):
        """Remove a note from the database."""
        self.ddb_connection.execute(
            "DELETE FROM notes WHERE vault_name = ? AND path = ?",
            (vault_name, str(path)),
        )

    def get_all_paths(self, vault_name: str) -> list[str]:
        """Get all indexed paths for a vault."""
        result = self.ddb_connection.execute(
            "SELECT path FROM notes WHERE vault_name = ?", (vault_name,)
        ).fetchall()
        return [row[0] for row in result]

    def get_hashes_for_paths(self, vault_name: str, paths: Sequence[str]) -> dict[str, str | None]:
        """
        Get content hashes for a list of paths.

        Returns a dict mapping path -> hash (or None if not found).
        """
        if not paths:
            return {}

        # Build query with parameterized IN clause
        placeholders = ", ".join("?" for _ in paths)
        query = f"SELECT path, content_hash FROM notes WHERE vault_name = ? AND path IN ({placeholders})"
        params = [vault_name, *paths]

        result = self.ddb_connection.execute(query, params).fetchall()
        return {row[0]: row[1] for row in result}

    def store_note(
        self,
        path: Path,
        vault_name: str,
        last_modified: float,
        content_hash: str,
        embedding: list[float],
    ):
        """
        Store a note in the database.
        NOTE: The path should be relative to the vault root.
        """
        # DuckDB claims 'Not implemented Error: Array Update is not supported' when attempting to overwrite an array.
        # So we delete the row first if it exists.
        self.ddb_connection.execute(
            "DELETE FROM notes WHERE vault_name = ? AND path = ?",
            (vault_name, str(path)),
        )
        self.ddb_connection.execute(
            "INSERT OR REPLACE INTO notes (path, vault_name, last_modified, content_hash, embedding) VALUES (?, ?, ?, ?, ?)",
            (str(path), vault_name, last_modified, content_hash, embedding),
        )

    def search(self, query_emb: torch.Tensor, top_k: int = 1) -> Sequence[tuple[str, Path]]:
        """
        Search for notes similar to a query embedding.
        """
        results = self.ddb_connection.execute(
            "SELECT vault_name, path FROM notes ORDER BY embedding <-> ? LIMIT ?",
            (query_emb, top_k),
        )
        results = [(r[0], Path(r[1])) for r in results.fetchall()]
        return results
