import hashlib
import time
from collections.abc import Sequence
from pathlib import Path

from obsidian_index.index.database import Database
from obsidian_index.index.encoder import Encoder
from obsidian_index.logger import logging

logger = logging.getLogger(__name__)


def compute_content_hash(content: str) -> str:
    """Compute a hash of the file content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class Indexer:
    database: Database
    vaults: dict[str, Path]
    encoder: Encoder
    model_batch_size: int

    def __init__(
        self,
        database: Database,
        vaults: dict[str, Path],
        encoder: Encoder,
        model_batch_size: int = 16,
    ):
        self.database = database
        self.vaults = vaults
        self.encoder = encoder
        self.model_batch_size = model_batch_size

    def ingest_paths(self, vault_name_paths: Sequence[tuple[str, Path]]):
        if not vault_name_paths:
            return

        logger.info("Processing %d paths", len(vault_name_paths))

        # Read file contents and compute hashes
        file_data: list[tuple[str, Path, str, str]] = []  # (vault_name, path, content, hash)
        for vault_name, path in vault_name_paths:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                content_hash = compute_content_hash(content)
                file_data.append((vault_name, path, content, content_hash))
            except Exception as e:
                logger.warning("Failed to read %s: %s", path, e)

        if not file_data:
            return

        # Group by vault to batch-fetch existing hashes
        vault_groups: dict[str, list[tuple[Path, str, str]]] = {}
        for vault_name, path, content, content_hash in file_data:
            if vault_name not in vault_groups:
                vault_groups[vault_name] = []
            vault_groups[vault_name].append((path, content, content_hash))

        # Check which files have changed
        files_to_index: list[tuple[str, Path, str, str]] = []  # (vault_name, path, content, hash)

        for vault_name, files in vault_groups.items():
            # Get relative paths for DB lookup
            vault_root = self.vaults[vault_name]
            rel_paths = [str(path.relative_to(vault_root)) for path, _, _ in files]

            # Fetch existing hashes
            existing_hashes = self.database.get_hashes_for_paths(vault_name, rel_paths)

            # Compare hashes
            for (path, content, new_hash), rel_path in zip(files, rel_paths, strict=True):
                existing_hash = existing_hashes.get(rel_path)
                if existing_hash == new_hash:
                    logger.debug("Skipping unchanged file: %s", rel_path)
                else:
                    files_to_index.append((vault_name, path, content, new_hash))

        skipped = len(file_data) - len(files_to_index)
        if skipped > 0:
            logger.info("Skipping %d unchanged files", skipped)

        if not files_to_index:
            logger.info("No files need indexing")
            return

        logger.info("Indexing %d files", len(files_to_index))

        # Extract texts for encoding
        texts = [content for _, _, content, _ in files_to_index]

        # Encode documents
        time_emb_start = time.time()
        embs = self.encoder.encode_documents(texts, batch_size=self.model_batch_size)
        time_emb_stop = time.time()
        logger.info("Embedding %d docs took %.2fs", len(texts), time_emb_stop - time_emb_start)

        # Store embeddings
        logger.info("Storing embeddings for %d paths", len(files_to_index))
        for (vault_name, path, _, content_hash), emb in zip(files_to_index, embs, strict=True):
            vault_rel_path = path.relative_to(self.vaults[vault_name])
            self.database.store_note(
                vault_rel_path,
                vault_name,
                path.stat().st_mtime,
                content_hash,
                emb,  # type: ignore
            )
