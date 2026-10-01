"""The port for turning text into vectors (CLAUDE.md §8.2, ADR-07).

There is no implementation in this package and there is not meant to be one yet.
The embedding model runs locally, inside the backend container, so that
case-derived text never reaches a second external service (ADR-07, ADR-10); it is
installed and wired manually in M4 as
`app.adapters.embeddings.sentence_transformer:SentenceTransformerEmbedder`.

`dim` matters beyond bookkeeping: it has to match the width of the `kb_chunks`
embedding column, which is created in M4 along with its index. Re-indexing the
whole knowledge base is the only way to change it (ADR-14).

Mock stages need no embeddings at all, which is why `EMBEDDING_PROVIDER` defaults
to empty and `PipelineDeps.embedder` is `None` unless a real stage asks for one.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    model_id: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector of length `dim` per input text, in order."""
        ...
