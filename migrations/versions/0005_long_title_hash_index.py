"""Usa índice hash para títulos normalizados longos.

Revision ID: 0005_long_title_hash_index
Revises: 0004_repository_harvesting
"""

from alembic import op

revision = "0005_long_title_hash_index"
down_revision = "0004_repository_harvesting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_articles_normalized_title", table_name="articles")
    op.execute(
        "CREATE INDEX ix_articles_normalized_title ON articles USING hash (normalized_title)"
    )


def downgrade() -> None:
    op.drop_index("ix_articles_normalized_title", table_name="articles")
    op.create_index("ix_articles_normalized_title", "articles", ["normalized_title"])
