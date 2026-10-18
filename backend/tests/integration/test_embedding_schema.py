# backend/tests/integration/test_embedding_schema.py
from sqlalchemy import text

from app.core.config import Settings


def test_embedding_column_matches_the_configured_dimension(db_session):
    dim = db_session.execute(
        text(
            "select atttypmod from pg_attribute where attrelid = 'kb_chunks'::regclass "
            "and attname = 'embedding' and not attisdropped"
        )
    ).scalar()
    assert dim == Settings().embedding_dim


def test_hnsw_cosine_index_exists(db_session):
    idx = db_session.execute(
        text("select indexdef from pg_indexes where indexname = 'ix_kb_chunks_embedding_hnsw'")
    ).scalar()
    assert idx and "hnsw" in idx and "vector_cosine_ops" in idx
