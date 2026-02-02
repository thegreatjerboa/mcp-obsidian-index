from collections.abc import Sequence

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from obsidian_index.index.models import EmbeddingModelConfig, get_model_config


def _get_device() -> str:
    """Auto-detect the best available device for inference."""
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class Encoder:
    model: SentenceTransformer
    model_config: EmbeddingModelConfig

    def __init__(self, model_config: EmbeddingModelConfig | None = None):
        if model_config is None:
            model_config = get_model_config()

        self.model_config = model_config
        device = _get_device()
        self.model = SentenceTransformer(
            model_config.model_id,
            device=device,
            trust_remote_code=model_config.trust_remote_code,
        )

    def encode_query(self, query: str) -> torch.Tensor | np.ndarray:
        """
        Encode a query into a vector.
        """
        text = self.model_config.query_prefix + query
        return self.model.encode(
            text,
            show_progress_bar=False,
        )

    def encode_documents(
        self, documents: Sequence[str], batch_size: int = 16
    ) -> torch.Tensor | np.ndarray:
        """
        Encode a sequence of documents into a matrix.
        """
        texts = [self.model_config.document_prefix + doc for doc in documents]
        return self.model.encode(texts, show_progress_bar=False, batch_size=batch_size)
