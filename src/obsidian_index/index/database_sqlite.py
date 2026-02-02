"""SQLite + sqlite-vec database implementation for vector storage.

This implementation supports concurrent access from multiple processes via WAL mode.
"""

import sqlite3
import struct
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import sqlite_vec
import torch

from obsidian_index.index.models import EmbeddingModelConfig, get_model_config
from obsidian_index.logger import logging

logger = logging.getLogger(__name__)

# Legacy model name from before model was configurable
LEGACY_MODEL_NAME = "paraphrase-MiniLM-L6-v2"

# SQLite file header (first 16 bytes)
SQLITE_HEADER = b"SQLite format 3\x00"


def _is_sqlite_database(path: Path) -> bool:
    """Check if a file is a SQLite database by reading its header."""
    if not path.exists():
        return True  # Non-existent file is fine for SQLite to create

    if path.stat().st_size == 0:
        return True  # Empty file is fine for SQLite

    try:
        with open(path, "rb") as f:
            header = f.read(16)
            return header == SQLITE_HEADER
    except Exception:
        return False


def _delete_legacy_duckdb(path: Path) -> bool:
    """Delete a legacy DuckDB database file if detected.

    Returns True if a DuckDB database was deleted.
    """
    if not path.exists():
        return False

    if _is_sqlite_database(path):
        return False

    # Not a SQLite database - assume it's DuckDB and delete it
    logger.warning(
        "Detected legacy DuckDB database at %s, deleting and creating fresh SQLite database...",
        path,
    )

    # Delete the main file and any associated files
    path.unlink()

    # DuckDB might have a .wal file
    wal_path = path.with_suffix(path.suffix + ".wal")
    if wal_path.exists():
        wal_path.unlink()

    return True


def _serialize_embedding(embedding: list[float] | np.ndarray | torch.Tensor) -> bytes:
    """Serialize an embedding to bytes for sqlite-vec."""
    if isinstance(embedding, torch.Tensor):
        embedding = embedding.cpu().numpy()
    if isinstance(embedding, np.ndarray):
        embedding = embedding.tolist()
    return struct.pack(f"{len(embedding)}f", *embedding)


def _deserialize_embedding(data: bytes) -> list[float]:
    """Deserialize bytes back to a float list."""
    count = len(data) // 4
    return list(struct.unpack(f"{count}f", data))


class Database:
    """SQLite + sqlite-vec database for vector storage with concurrent access support."""

    connection: sqlite3.Connection
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
        self.database_path = database_path
        self.read_only = read_only

        # Check for and delete legacy DuckDB database
        if not read_only:
            _delete_legacy_duckdb(database_path)

        # Connect with URI mode for read-only support
        if read_only:
            uri = f"file:{database_path}?mode=ro"
            self.connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
        else:
            self.connection = sqlite3.connect(database_path, check_same_thread=False)

        # Enable WAL mode for concurrent access
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute("PRAGMA busy_timeout=5000")

        # Load sqlite-vec extension
        self.connection.enable_load_extension(True)
        sqlite_vec.load(self.connection)
        self.connection.enable_load_extension(False)

        if not self.read_only:
            self.initialize()

    def _table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        result = self.connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return result[0] > 0

    def _column_exists(self, table_name: str, column_name: str) -> bool:
        """Check if a column exists in a table."""
        cursor = self.connection.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        return column_name in columns

    def _get_stored_model(self) -> str | None:
        """Get the model name stored in the metadata table."""
        if not self._table_exists("metadata"):
            return None
        result = self.connection.execute(
            "SELECT value FROM metadata WHERE key = 'model_name'"
        ).fetchone()
        return result[0] if result else None

    def _set_stored_model(self, model_name: str):
        """Store the model name in the metadata table."""
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('model_name', ?)",
            (model_name,),
        )
        self.connection.commit()

    def _handle_model_change(self, stored_model: str):
        """Handle a change in embedding model by clearing and recreating tables."""
        logger.warning(
            "Model changed from '%s' to '%s', clearing index and reindexing...",
            stored_model,
            self.model_config.name,
        )

        # Drop existing tables
        self.connection.execute("DROP TABLE IF EXISTS notes")
        self.connection.execute("DROP TABLE IF EXISTS notes_vec")

        # Update stored model
        self._set_stored_model(self.model_config.name)

        # Create tables with new dimensions
        self._create_notes_tables()

    def _create_notes_tables(self):
        """Create the notes tables with the current model's dimensions."""
        # Main notes table for metadata
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                vault_name TEXT NOT NULL,
                last_modified REAL,
                content_hash TEXT,
                UNIQUE(vault_name, path)
            )
        """)

        # Create index for faster lookups
        self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_notes_vault_path
            ON notes(vault_name, path)
        """)

        # Virtual table for vector embeddings
        self.connection.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_vec USING vec0(
                note_id INTEGER PRIMARY KEY,
                embedding float[{self.model_config.dimensions}]
            )
        """)

        self.connection.commit()

    def _create_primary_lock_table(self):
        """Create the primary_lock table for multi-instance coordination."""
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS primary_lock (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                holder TEXT NOT NULL,
                heartbeat REAL NOT NULL
            )
        """)
        self.connection.commit()

    def initialize(self):
        """Perform any necessary initialization of the database."""
        # Ensure metadata table exists
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        self.connection.commit()

        # Create primary lock table for coordination
        self._create_primary_lock_table()

        # Check if model has changed
        stored_model = self._get_stored_model()

        if stored_model is None:
            # Fresh database
            self._set_stored_model(self.model_config.name)
            self._create_notes_tables()
        elif stored_model != self.model_config.name:
            # Model changed - need to clear and reindex
            self._handle_model_change(stored_model)
        else:
            # Same model - just ensure tables exist
            self._create_notes_tables()

    def num_notes(self) -> int:
        """Get the total number of notes in the database."""
        result = self.connection.execute("SELECT COUNT(*) FROM notes").fetchone()
        return result[0]

    def get_most_recent_seen_timestamp(self, vault_name: str) -> float | None:
        """Get the most recent seen timestamp for a vault."""
        result = self.connection.execute(
            "SELECT MAX(last_modified) FROM notes WHERE vault_name = ?", (vault_name,)
        ).fetchone()
        return result[0]

    def delete_note(self, vault_name: str, path: Path):
        """Remove a note from the database."""
        # Get the note id first
        result = self.connection.execute(
            "SELECT id FROM notes WHERE vault_name = ? AND path = ?",
            (vault_name, str(path)),
        ).fetchone()

        if result:
            note_id = result[0]
            # Delete from vector table first
            self.connection.execute("DELETE FROM notes_vec WHERE note_id = ?", (note_id,))
            # Delete from notes table
            self.connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            self.connection.commit()

    def get_all_paths(self, vault_name: str) -> list[str]:
        """Get all indexed paths for a vault."""
        result = self.connection.execute(
            "SELECT path FROM notes WHERE vault_name = ?", (vault_name,)
        ).fetchall()
        return [row[0] for row in result]

    def get_hashes_for_paths(self, vault_name: str, paths: Sequence[str]) -> dict[str, str | None]:
        """Get content hashes for a list of paths.

        Returns a dict mapping path -> hash (or None if not found).
        """
        if not paths:
            return {}

        # Build query with parameterized IN clause
        placeholders = ", ".join("?" for _ in paths)
        query = f"SELECT path, content_hash FROM notes WHERE vault_name = ? AND path IN ({placeholders})"
        params = [vault_name, *paths]

        result = self.connection.execute(query, params).fetchall()
        return {row[0]: row[1] for row in result}

    def store_note(
        self,
        path: Path,
        vault_name: str,
        last_modified: float,
        content_hash: str,
        embedding: list[float] | np.ndarray | torch.Tensor,
    ):
        """Store a note in the database.

        NOTE: The path should be relative to the vault root.
        """
        path_str = str(path)

        # Check if note exists
        existing = self.connection.execute(
            "SELECT id FROM notes WHERE vault_name = ? AND path = ?",
            (vault_name, path_str),
        ).fetchone()

        if existing:
            note_id = existing[0]
            # Update existing note
            self.connection.execute(
                """UPDATE notes
                   SET last_modified = ?, content_hash = ?
                   WHERE id = ?""",
                (last_modified, content_hash, note_id),
            )
            # Delete old embedding
            self.connection.execute("DELETE FROM notes_vec WHERE note_id = ?", (note_id,))
        else:
            # Insert new note
            cursor = self.connection.execute(
                """INSERT INTO notes (path, vault_name, last_modified, content_hash)
                   VALUES (?, ?, ?, ?)""",
                (path_str, vault_name, last_modified, content_hash),
            )
            note_id = cursor.lastrowid

        # Insert embedding
        embedding_bytes = _serialize_embedding(embedding)
        self.connection.execute(
            "INSERT INTO notes_vec (note_id, embedding) VALUES (?, ?)",
            (note_id, embedding_bytes),
        )
        self.connection.commit()

    def search(
        self, query_emb: torch.Tensor | np.ndarray, top_k: int = 10
    ) -> Sequence[tuple[str, Path]]:
        """Search for notes similar to a query embedding."""
        query_bytes = _serialize_embedding(query_emb)

        # sqlite-vec requires k=? constraint for KNN queries
        results = self.connection.execute(
            """
            SELECT n.vault_name, n.path
            FROM notes_vec v
            JOIN notes n ON v.note_id = n.id
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY distance
            """,
            (query_bytes, top_k),
        ).fetchall()

        return [(r[0], Path(r[1])) for r in results]

    # Primary lock methods for multi-instance coordination

    def try_claim_primary(self, instance_id: str, current_time: float) -> bool:
        """Try to claim the primary role.

        Returns True if this instance is now the primary.
        """
        try:
            # Try to insert (first claim)
            self.connection.execute(
                "INSERT INTO primary_lock (id, holder, heartbeat) VALUES (1, ?, ?)",
                (instance_id, current_time),
            )
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            # Row exists, check if we can take over
            result = self.connection.execute(
                "SELECT holder, heartbeat FROM primary_lock WHERE id = 1"
            ).fetchone()

            if result is None:
                return False

            holder, heartbeat = result

            # If we're already the holder, update heartbeat
            if holder == instance_id:
                self.connection.execute(
                    "UPDATE primary_lock SET heartbeat = ? WHERE id = 1",
                    (current_time,),
                )
                self.connection.commit()
                return True

            # Check if current holder is stale (15 second threshold)
            if current_time - heartbeat > 15.0:
                # Take over
                self.connection.execute(
                    "UPDATE primary_lock SET holder = ?, heartbeat = ? WHERE id = 1",
                    (instance_id, current_time),
                )
                self.connection.commit()
                logger.info(
                    "Took over primary role from stale holder (last heartbeat: %.1fs ago)",
                    current_time - heartbeat,
                )
                return True

            return False

    def update_heartbeat(self, instance_id: str, current_time: float) -> bool:
        """Update the heartbeat for the primary instance.

        Returns True if this instance is still the primary.
        """
        cursor = self.connection.execute(
            "UPDATE primary_lock SET heartbeat = ? WHERE id = 1 AND holder = ?",
            (current_time, instance_id),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def release_primary(self, instance_id: str):
        """Release the primary role if we hold it."""
        self.connection.execute(
            "DELETE FROM primary_lock WHERE id = 1 AND holder = ?",
            (instance_id,),
        )
        self.connection.commit()

    def is_primary_stale(self, stale_threshold: float = 15.0) -> bool:
        """Check if the current primary holder is stale.

        Returns True if there is no primary or if the primary's heartbeat
        is older than stale_threshold seconds.
        """
        import time

        result = self.connection.execute(
            "SELECT heartbeat FROM primary_lock WHERE id = 1"
        ).fetchone()

        if result is None:
            return True

        return time.time() - result[0] > stale_threshold

    def get_primary_holder(self) -> tuple[str, float] | None:
        """Get the current primary holder info.

        Returns (holder_id, heartbeat) or None if no primary.
        """
        result = self.connection.execute(
            "SELECT holder, heartbeat FROM primary_lock WHERE id = 1"
        ).fetchone()
        return result if result else None

    def close(self):
        """Close the database connection."""
        self.connection.close()
