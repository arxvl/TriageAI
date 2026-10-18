"""Local sentence-embedding provider (M4). CPU by default, L2-normalised vectors.

Normalised vectors make cosine similarity a dot product, so the pgvector cosine
operator (<=>) and a plain dot product agree: score = 1 - distance.
"""

from __future__ import annotations

import threading


class SentenceTransformerEmbedder:
    _lock = threading.Lock()
    _models: dict[tuple[str, str], object] = {}  # shared by every instance in the process

    def __init__(self, model_id: str, dim: int, device: str = "cpu", batch_size: int = 32):
        self.model_id, self.dim, self.device, self.batch_size = model_id, dim, device, batch_size

    @classmethod
    def from_settings(cls, settings, deps=None) -> SentenceTransformerEmbedder:
        return cls(
            settings.embedding_model,
            settings.embedding_dim,
            settings.embedding_device,
            settings.embedding_batch_size,
        )

    def _load(self):
        key = (self.model_id, self.device)
        with self._lock:
            model = self._models.get(key)
            if model is None:
                from sentence_transformers import (
                    SentenceTransformer,  # lazy: importing torch is slow
                )

                model = SentenceTransformer(self.model_id, device=self.device)
                # Recent releases renamed the method; support both so a
                # version bump never breaks us.
                get_dim = (
                    getattr(model, "get_embedding_dimension", None)
                    or model.get_sentence_embedding_dimension
                )
                actual = get_dim()
                if actual != self.dim:
                    raise RuntimeError(
                        f"EMBEDDING_DIM={self.dim} but {self.model_id} produces {actual}. "
                        "The vector(N) column and the setting must both match the model."
                    )
                self._models[key] = model
        return model

    @property
    def max_seq_length(self) -> int:
        """Longest input, in word-pieces, before the model silently truncates."""
        return int(self._load().max_seq_length)

    def token_count(self, texts: list[str]) -> list[int]:
        """Word-piece count per text, so chunk sizes can be checked against max_seq_length."""
        tok = self._load().tokenizer
        return [len(ids) for ids in tok(texts, add_special_tokens=True)["input_ids"]]

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Pass the texts positionally: the keyword was renamed
        # (sentences -> inputs) between releases.
        vecs = self._load().encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vecs.tolist()
