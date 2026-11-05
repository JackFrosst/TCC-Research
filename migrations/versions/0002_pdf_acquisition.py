"""Adiciona aquisição e validação de PDFs Open Access.

Revision ID: 0002_pdf_acquisition
Revises: 0001_discovery_core
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_pdf_acquisition"
down_revision = "0001_discovery_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fulltext_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("article_id", sa.String(36), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("landing_page_url", sa.Text()),
        sa.Column("license", sa.String(100)),
        sa.Column("version", sa.String(100)),
        sa.Column("host_type", sa.String(50)),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("article_id", "source_url"),
    )
    op.create_index("ix_fulltext_candidates_article_id", "fulltext_candidates", ["article_id"])

    op.create_table(
        "download_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "candidate_id", sa.String(36), sa.ForeignKey("fulltext_candidates.id"), nullable=False
        ),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("bytes_downloaded", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64)),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_download_attempts_candidate_id", "download_attempts", ["candidate_id"])

    op.create_table(
        "fulltext_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("article_id", sa.String(36), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column(
            "candidate_id", sa.String(36), sa.ForeignKey("fulltext_candidates.id"), nullable=False
        ),
        sa.Column("storage_path", sa.Text(), nullable=False, unique=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("license", sa.String(100)),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("validation_status", sa.String(50), nullable=False),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("article_id", "sha256"),
    )
    op.create_index("ix_fulltext_assets_article_id", "fulltext_assets", ["article_id"])
    op.create_index("ix_fulltext_assets_candidate_id", "fulltext_assets", ["candidate_id"])
    op.create_index("ix_fulltext_assets_sha256", "fulltext_assets", ["sha256"])

    op.create_table(
        "pdf_validation_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("fulltext_assets.id"), nullable=False),
        sa.Column("signature_valid", sa.Boolean(), nullable=False),
        sa.Column("opens_valid", sa.Boolean(), nullable=False),
        sa.Column("encrypted", sa.Boolean(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pdf_validation_results_asset_id", "pdf_validation_results", ["asset_id"])


def downgrade() -> None:
    op.drop_table("pdf_validation_results")
    op.drop_table("fulltext_assets")
    op.drop_table("download_attempts")
    op.drop_table("fulltext_candidates")
