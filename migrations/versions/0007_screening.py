"""Adiciona priorização semântica auditável.

Revision ID: 0007_screening
Revises: 0006_title_prefix_index
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_screening"
down_revision = "0006_title_prefix_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "screening_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "protocol_id", sa.String(36), sa.ForeignKey("review_protocols.id"), nullable=False
        ),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("model", sa.String(300), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("articles_processed", sa.Integer(), nullable=False),
        sa.Column("high_priority", sa.Integer(), nullable=False),
        sa.Column("medium_priority", sa.Integer(), nullable=False),
        sa.Column("low_priority", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_screening_runs_project_id", "screening_runs", ["project_id"])
    op.create_index("ix_screening_runs_protocol_id", "screening_runs", ["protocol_id"])
    op.create_table(
        "screening_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "screening_run_id",
            sa.String(36),
            sa.ForeignKey("screening_runs.id"),
            nullable=False,
        ),
        sa.Column("article_id", sa.String(36), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("decision", sa.String(50), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column("criteria_scores", sa.JSON(), nullable=False),
        sa.Column("content_basis", sa.String(30), nullable=False),
        sa.Column("requires_human_review", sa.Boolean(), nullable=False),
        sa.Column("model", sa.String(300), nullable=False),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("screening_run_id", "article_id"),
    )
    op.create_index(
        "ix_screening_decisions_screening_run_id",
        "screening_decisions",
        ["screening_run_id"],
    )
    op.create_index("ix_screening_decisions_article_id", "screening_decisions", ["article_id"])
    op.create_index(
        "ix_screening_decisions_run_score",
        "screening_decisions",
        ["screening_run_id", "relevance_score"],
    )


def downgrade() -> None:
    op.drop_table("screening_decisions")
    op.drop_table("screening_runs")
