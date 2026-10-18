"""m4 kb_chunks embedding column and hnsw index

Revision ID: c2b9970f3c53
Revises: 0004
Create Date: 2026-10-18 12:21:05.835817

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c2b9970f3c53"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The init script only enabled the extension in the first database; the test database
    # that P02's fixture creates later needs it too.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE kb_chunks ADD COLUMN embedding vector(384)")
    op.execute("ALTER TABLE kb_chunks ADD COLUMN embedding_model text")
    op.execute(
        "CREATE INDEX ix_kb_chunks_embedding_hnsw ON kb_chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_kb_chunks_embedding_hnsw")
    op.execute("ALTER TABLE kb_chunks DROP COLUMN IF EXISTS embedding_model")
    op.execute("ALTER TABLE kb_chunks DROP COLUMN IF EXISTS embedding")
