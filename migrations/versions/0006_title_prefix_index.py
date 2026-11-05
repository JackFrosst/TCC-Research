"""Acelera a seleção de candidatos de deduplicação por prefixo.

Revision ID: 0006_title_prefix_index
Revises: 0005_long_title_hash_index
"""

from alembic import op

revision = "0006_title_prefix_index"
down_revision = "0005_long_title_hash_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_articles_normalized_title_prefix "
        "ON articles ((left(normalized_title, 16)))"
    )


def downgrade() -> None:
    op.drop_index("ix_articles_normalized_title_prefix", table_name="articles")
