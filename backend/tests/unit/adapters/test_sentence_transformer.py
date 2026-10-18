"""Adapter tests. A fake `sentence_transformers` module stands in for the real one,
so these run in CI with no torch, no download and no network."""

import sys
import types

import numpy as np
import pytest

from app.adapters.embeddings.sentence_transformer import SentenceTransformerEmbedder


class FakeModel:
    max_seq_length = 256

    def __init__(self, name, device=None, dim=384, new_api=True):
        self.name, self.device, self._dim = name, device, dim
        self.calls = []
        if new_api:
            self.get_embedding_dimension = lambda: self._dim
        else:
            self.get_sentence_embedding_dimension = lambda: self._dim
        self.tokenizer = lambda texts, add_special_tokens=True: {
            "input_ids": [[0] * (len(t.split()) + 2) for t in texts]
        }

    def encode(self, texts, **kw):
        self.calls.append(kw)
        out = np.ones((len(texts), self._dim), dtype="float32")
        return out / np.linalg.norm(out, axis=1, keepdims=True)


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(SentenceTransformerEmbedder, "_models", {})
    built = []

    def factory(dim=384, new_api=True):
        mod = types.ModuleType("sentence_transformers")

        def ST(name, device=None):
            m = FakeModel(name, device, dim, new_api)
            built.append(m)
            return m

        mod.SentenceTransformer = ST
        monkeypatch.setitem(sys.modules, "sentence_transformers", mod)

    factory()
    return types.SimpleNamespace(built=built, factory=factory)


def test_embed_returns_plain_lists_and_requests_normalisation(fresh_cache):
    e = SentenceTransformerEmbedder("m", 384)
    out = e.embed(["a", "b"])
    assert isinstance(out, list) and isinstance(out[0], list) and len(out[0]) == 384
    assert abs(sum(x * x for x in out[0]) - 1.0) < 1e-5
    assert fresh_cache.built[0].calls[0]["normalize_embeddings"] is True


def test_empty_input_does_not_load_the_model(fresh_cache):
    assert SentenceTransformerEmbedder("m", 384).embed([]) == []
    assert fresh_cache.built == []


def test_model_loads_once_and_is_shared_between_instances(fresh_cache):
    SentenceTransformerEmbedder("m", 384).embed(["x"])
    SentenceTransformerEmbedder("m", 384).embed(
        ["y"]
    )  # e.g. the lifespan warm-up, then deps.embedder
    assert len(fresh_cache.built) == 1


def test_different_models_do_not_share_a_cache_slot(fresh_cache):
    SentenceTransformerEmbedder("a", 384).embed(["x"])
    SentenceTransformerEmbedder("b", 384).embed(["x"])
    assert [m.name for m in fresh_cache.built] == ["a", "b"]


def test_dimension_mismatch_fails_loudly(fresh_cache):
    fresh_cache.factory(dim=768)
    with pytest.raises(RuntimeError, match="EMBEDDING_DIM=384"):
        SentenceTransformerEmbedder("m", 384).embed(["x"])


def test_old_dimension_method_name_still_works(fresh_cache):
    fresh_cache.factory(new_api=False)
    assert len(SentenceTransformerEmbedder("m", 384).embed(["x"])[0]) == 384


def test_max_seq_length_and_token_count(fresh_cache):
    e = SentenceTransformerEmbedder("m", 384)
    assert e.max_seq_length == 256
    assert e.token_count(["one two three"]) == [5]


def test_from_settings():
    cfg = types.SimpleNamespace(
        embedding_model="m", embedding_dim=384, embedding_device="cpu", embedding_batch_size=16
    )
    e = SentenceTransformerEmbedder.from_settings(cfg)
    assert (e.model_id, e.dim, e.device, e.batch_size) == ("m", 384, "cpu", 16)
