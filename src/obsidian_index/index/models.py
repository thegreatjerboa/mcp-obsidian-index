"""Embedding model registry and configuration."""

import os
from dataclasses import dataclass


@dataclass
class EmbeddingModelConfig:
    """Configuration for an embedding model."""

    name: str  # Short name: "all-MiniLM-L6-v2"
    model_id: str  # HuggingFace ID: "sentence-transformers/all-MiniLM-L6-v2"
    dimensions: int
    max_tokens: int
    trust_remote_code: bool = False  # Required for nomic
    document_prefix: str = ""  # Prepended to documents before encoding
    query_prefix: str = ""  # Prepended to queries before encoding


SUPPORTED_MODELS: dict[str, EmbeddingModelConfig] = {
    "paraphrase-MiniLM-L6-v2": EmbeddingModelConfig(
        name="paraphrase-MiniLM-L6-v2",
        model_id="sentence-transformers/paraphrase-MiniLM-L6-v2",
        dimensions=384,
        max_tokens=256,
    ),
    "all-MiniLM-L6-v2": EmbeddingModelConfig(
        name="all-MiniLM-L6-v2",
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        dimensions=384,
        max_tokens=256,
    ),
    "bge-small-en-v1.5": EmbeddingModelConfig(
        name="bge-small-en-v1.5",
        model_id="BAAI/bge-small-en-v1.5",
        dimensions=384,
        max_tokens=512,
    ),
    "all-mpnet-base-v2": EmbeddingModelConfig(
        name="all-mpnet-base-v2",
        model_id="sentence-transformers/all-mpnet-base-v2",
        dimensions=768,
        max_tokens=384,
    ),
    "nomic-embed-text-v1": EmbeddingModelConfig(
        name="nomic-embed-text-v1",
        model_id="nomic-ai/nomic-embed-text-v1",
        dimensions=768,
        max_tokens=8192,
        trust_remote_code=True,
        document_prefix="search_document: ",
        query_prefix="search_query: ",
    ),
}

DEFAULT_MODEL = "paraphrase-MiniLM-L6-v2"

ENV_VAR_NAME = "OBSIDIAN_INDEX_MODEL"


def get_model_config(model_name: str | None = None) -> EmbeddingModelConfig:
    """
    Get the model configuration for the specified model name.

    Args:
        model_name: The name of the model. If None, uses the environment variable
                   OBSIDIAN_INDEX_MODEL, falling back to DEFAULT_MODEL.

    Returns:
        The model configuration.

    Raises:
        ValueError: If the model name is not supported.
    """
    if model_name is None:
        model_name = os.environ.get(ENV_VAR_NAME, DEFAULT_MODEL)

    if model_name not in SUPPORTED_MODELS:
        supported = ", ".join(SUPPORTED_MODELS.keys())
        raise ValueError(f"Unsupported model: {model_name}. Supported models: {supported}")

    return SUPPORTED_MODELS[model_name]
