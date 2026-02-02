from collections.abc import Sequence

import numpy as np
import torch
from sentence_transformers import SentenceTransformer


def _get_device() -> str:
    """Auto-detect the best available device for inference."""
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class Encoder:
    model_minilm_l6_v2: SentenceTransformer

    def __init__(self):
        device = _get_device()
        self.model_minilm_l6_v2 = SentenceTransformer(
            "sentence-transformers/paraphrase-MiniLM-L6-v2",
            device=device,
        )

    def encode_query(self, query: str) -> torch.Tensor | np.ndarray:
        """
        Encode a query into a vector.
        """
        return self.model_minilm_l6_v2.encode(
            query,
            show_progress_bar=False,
        )

    def encode_documents(
        self, documents: Sequence[str], batch_size: int = 16
    ) -> torch.Tensor | np.ndarray:
        """
        Encode a sequence of documents into a matrix.
        """
        return self.model_minilm_l6_v2.encode(
            list(documents), show_progress_bar=False, batch_size=batch_size
        )
