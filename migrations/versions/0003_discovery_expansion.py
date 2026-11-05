"""Expande descoberta, métricas, proveniência e deduplicação.

Revision ID: 0003_discovery_expansion
Revises: 0002_pdf_acquisition
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_discovery_expansion"
down_revision = "0002_pdf_acquisition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "articles", sa.Column("external_ids", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column("articles", sa.Column("document_type", sa.String(100)))
    op.add_column("articles", sa.Column("peer_reviewed", sa.Boolean()))
    op.add_column(
        "articles", sa.Column("oa_locations", sa.JSON(), nullable=False, server_default="[]")
    )
    op.add_column(
        "source_records",
        sa.Column("discovery_method", sa.String(50), nullable=False, server_default="keyword"),
    )
    op.add_column(
        "source_records",
        sa.Column("seed_article_id", sa.String(36), sa.ForeignKey("articles.id")),
    )
    op.add_column(
        "source_records", sa.Column("depth", sa.Integer(), nullable=False, server_default="0")
    )

    op.create_table(
        "search_run_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("search_run_id", sa.String(36), sa.ForeignKey("search_runs.id"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("query_code", sa.String(100), nullable=False),
        sa.Column("pages_fetched", sa.Integer(), nullable=False),
        sa.Column("records_returned", sa.Integer(), nullable=False),
        sa.Column("records_ingested", sa.Integer(), nullable=False),
        sa.Column("articles_created", sa.Integer(), nullable=False),
        sa.Column("duplicates", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("last_cursor", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.UniqueConstraint("search_run_id", "provider", "query_code"),
    )
    op.create_index("ix_search_run_metrics_search_run_id", "search_run_metrics", ["search_run_id"])

    op.create_table(
        "article_relations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_article_id", sa.String(36), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("target_article_id", sa.String(36), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("relation_type", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_article_id", "target_article_id", "relation_type"),
    )
    op.create_index(
        "ix_article_relations_source_article_id", "article_relations", ["source_article_id"]
    )
    op.create_index(
        "ix_article_relations_target_article_id", "article_relations", ["target_article_id"]
    )
    op.create_table(
        "deduplication_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("article_a_id", sa.String(36), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("article_b_id", sa.String(36), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("similarity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("decided_by", sa.String(200)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("article_a_id", "article_b_id"),
    )
    op.create_index(
        "ix_deduplication_candidates_project_id", "deduplication_candidates", ["project_id"]
    )
    op.create_index(
        "ix_deduplication_candidates_article_a_id",
        "deduplication_candidates",
        ["article_a_id"],
    )
    op.create_index(
        "ix_deduplication_candidates_article_b_id",
        "deduplication_candidates",
        ["article_b_id"],
    )


def downgrade() -> None:
    op.drop_table("deduplication_candidates")
    op.drop_table("article_relations")
    op.drop_table("search_run_metrics")
    op.drop_column("source_records", "depth")
    op.drop_column("source_records", "seed_article_id")
    op.drop_column("source_records", "discovery_method")
    op.drop_column("articles", "oa_locations")
    op.drop_column("articles", "peer_reviewed")
    op.drop_column("articles", "document_type")
    op.drop_column("articles", "external_ids")
