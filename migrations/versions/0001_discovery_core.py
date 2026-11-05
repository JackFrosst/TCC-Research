"""Cria o núcleo de descoberta acadêmica.

Revision ID: 0001_discovery_core
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_discovery_core"
down_revision = None
branch_labels = None
depends_on = None


protocol_status = sa.Enum("draft", "approved", "superseded", name="protocolstatus")
search_status = sa.Enum("running", "completed", "failed", name="searchrunstatus")


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("technical_focus", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_projects_slug", "projects", ["slug"])

    op.create_table(
        "review_protocols",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", protocol_status, nullable=False),
        sa.Column("research_question", sa.Text(), nullable=False),
        sa.Column("year_from", sa.Integer(), nullable=False),
        sa.Column("year_to", sa.Integer(), nullable=False),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("inclusion_criteria", sa.JSON(), nullable=False),
        sa.Column("exclusion_criteria", sa.JSON(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "version"),
    )
    op.create_index("ix_review_protocols_project_id", "review_protocols", ["project_id"])

    op.create_table(
        "search_queries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "protocol_id", sa.String(36), sa.ForeignKey("review_protocols.id"), nullable=False
        ),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.UniqueConstraint("protocol_id", "code"),
    )
    op.create_index("ix_search_queries_protocol_id", "search_queries", ["protocol_id"])

    op.create_table(
        "search_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "protocol_id", sa.String(36), sa.ForeignKey("review_protocols.id"), nullable=False
        ),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("providers", sa.JSON(), nullable=False),
        sa.Column("status", search_status, nullable=False),
        sa.Column("records_received", sa.Integer(), nullable=False),
        sa.Column("articles_created", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_search_runs_protocol_id", "search_runs", ["protocol_id"])

    op.create_table(
        "articles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("normalized_title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text()),
        sa.Column("year", sa.Integer()),
        sa.Column("journal", sa.Text()),
        sa.Column("doi", sa.String(300)),
        sa.Column("language", sa.String(20)),
        sa.Column("authors", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "code"),
        sa.UniqueConstraint("project_id", "doi"),
    )
    op.create_index("ix_articles_project_id", "articles", ["project_id"])
    op.create_index("ix_articles_normalized_title", "articles", ["normalized_title"])
    op.create_index("ix_articles_doi", "articles", ["doi"])

    op.create_table(
        "source_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("search_run_id", sa.String(36), sa.ForeignKey("search_runs.id"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_id", sa.String(500), nullable=False),
        sa.Column("query_code", sa.String(20), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("search_run_id", "provider", "provider_id"),
    )
    op.create_index("ix_source_records_search_run_id", "source_records", ["search_run_id"])

    op.create_table(
        "article_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("article_id", sa.String(36), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_id", sa.String(500), nullable=False),
        sa.Column(
            "source_record_id", sa.String(36), sa.ForeignKey("source_records.id"), nullable=False
        ),
        sa.UniqueConstraint("article_id", "provider", "provider_id"),
    )
    op.create_index("ix_article_sources_article_id", "article_sources", ["article_id"])

    op.create_table(
        "workflow_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflow_events_project_id", "workflow_events", ["project_id"])


def downgrade() -> None:
    op.drop_table("workflow_events")
    op.drop_table("article_sources")
    op.drop_table("source_records")
    op.drop_table("articles")
    op.drop_table("search_runs")
    op.drop_table("search_queries")
    op.drop_table("review_protocols")
    op.drop_table("projects")
    search_status.drop(op.get_bind(), checkfirst=True)
    protocol_status.drop(op.get_bind(), checkfirst=True)
