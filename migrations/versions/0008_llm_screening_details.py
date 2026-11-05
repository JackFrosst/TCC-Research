"""Adiciona justificativas e evidencias da triagem generativa.

Revision ID: 0008_llm_screening_details
Revises: 0007_screening
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_llm_screening_details"
down_revision = "0007_screening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("screening_decisions", sa.Column("reason", sa.Text()))
    op.add_column(
        "screening_decisions",
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column(
        "screening_decisions",
        sa.Column(
            "uncertainties", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
    )
    op.add_column("screening_decisions", sa.Column("exclusion_code", sa.String(20)))


def downgrade() -> None:
    op.drop_column("screening_decisions", "exclusion_code")
    op.drop_column("screening_decisions", "uncertainties")
    op.drop_column("screening_decisions", "evidence")
    op.drop_column("screening_decisions", "reason")
