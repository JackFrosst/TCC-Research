"""Adiciona coleta auditável de repositórios acadêmicos.

Revision ID: 0004_repository_harvesting
Revises: 0003_discovery_expansion
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_repository_harvesting"
down_revision = "0003_discovery_expansion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repository_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("domain", sa.String(300), nullable=False),
        sa.Column("acquisition_method", sa.String(50), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("crawl_delay_seconds", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_repository_sources_slug", "repository_sources", ["slug"])
    op.create_table(
        "harvest_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id", sa.String(36), sa.ForeignKey("repository_sources.id"), nullable=False
        ),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column(
            "status",
            sa.Enum("running", "completed", "failed", name="harvestrunstatus"),
            nullable=False,
        ),
        sa.Column("checkpoint", sa.JSON(), nullable=False),
        sa.Column("records_received", sa.Integer(), nullable=False),
        sa.Column("records_created", sa.Integer(), nullable=False),
        sa.Column("records_updated", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_harvest_runs_source_id", "harvest_runs", ["source_id"])
    op.create_table(
        "harvested_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id", sa.String(36), sa.ForeignKey("repository_sources.id"), nullable=False
        ),
        sa.Column("external_id", sa.String(500), nullable=False),
        sa.Column("canonical_url", sa.Text()),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("normalized_title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text()),
        sa.Column("year", sa.Integer()),
        sa.Column("journal", sa.Text()),
        sa.Column("doi", sa.String(300)),
        sa.Column("language", sa.String(20)),
        sa.Column("authors", sa.JSON(), nullable=False),
        sa.Column("external_ids", sa.JSON(), nullable=False),
        sa.Column("document_type", sa.String(100)),
        sa.Column("peer_reviewed", sa.Boolean()),
        sa.Column("oa_locations", sa.JSON(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "external_id"),
    )
    for name, columns in {
        "ix_harvested_records_source_id": ["source_id"],
        "ix_harvested_records_normalized_title": ["normalized_title"],
        "ix_harvested_records_year": ["year"],
        "ix_harvested_records_doi": ["doi"],
    }.items():
        op.create_index(name, "harvested_records", columns)


def downgrade() -> None:
    op.drop_table("harvested_records")
    op.drop_table("harvest_runs")
    op.drop_table("repository_sources")
    op.execute("DROP TYPE IF EXISTS harvestrunstatus")
