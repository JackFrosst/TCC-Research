from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class ProtocolStatus(str, enum.Enum):
    draft = "DRAFT"
    approved = "APPROVED"
    superseded = "SUPERSEDED"


class SearchRunStatus(str, enum.Enum):
    running = "RUNNING"
    completed = "COMPLETED"
    failed = "FAILED"


class HarvestRunStatus(str, enum.Enum):
    running = "RUNNING"
    completed = "COMPLETED"
    failed = "FAILED"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    technical_focus: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    protocols: Mapped[list[ReviewProtocol]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    articles: Mapped[list[Article]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ReviewProtocol(Base):
    __tablename__ = "review_protocols"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[ProtocolStatus] = mapped_column(
        Enum(ProtocolStatus), default=ProtocolStatus.draft
    )
    research_question: Mapped[str] = mapped_column(Text)
    year_from: Mapped[int] = mapped_column(Integer)
    year_to: Mapped[int] = mapped_column(Integer)
    languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    inclusion_criteria: Mapped[list[dict]] = mapped_column(JSON, default=list)
    exclusion_criteria: Mapped[list[dict]] = mapped_column(JSON, default=list)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="protocols")
    queries: Mapped[list[SearchQuery]] = relationship(
        back_populates="protocol", cascade="all, delete-orphan"
    )
    runs: Mapped[list[SearchRun]] = relationship(back_populates="protocol")

    __table_args__ = (UniqueConstraint("project_id", "version"),)


class SearchQuery(Base):
    __tablename__ = "search_queries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    protocol_id: Mapped[str] = mapped_column(ForeignKey("review_protocols.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    query_text: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), default="en")

    protocol: Mapped[ReviewProtocol] = relationship(back_populates="queries")

    __table_args__ = (UniqueConstraint("protocol_id", "code"),)


class SearchRun(Base):
    __tablename__ = "search_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    protocol_id: Mapped[str] = mapped_column(ForeignKey("review_protocols.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    providers: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[SearchRunStatus] = mapped_column(Enum(SearchRunStatus))
    records_received: Mapped[int] = mapped_column(Integer, default=0)
    articles_created: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    protocol: Mapped[ReviewProtocol] = relationship(back_populates="runs")
    source_records: Mapped[list[SourceRecord]] = relationship(back_populates="search_run")
    metrics: Mapped[list[SearchRunMetric]] = relationship(
        back_populates="search_run", cascade="all, delete-orphan"
    )


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(Text, index=True)
    abstract: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    journal: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(String(300), index=True)
    language: Mapped[str | None] = mapped_column(String(20))
    authors: Mapped[list[dict]] = mapped_column(JSON, default=list)
    external_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    document_type: Mapped[str | None] = mapped_column(String(100))
    peer_reviewed: Mapped[bool | None] = mapped_column()
    oa_locations: Mapped[list[dict]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="articles")
    sources: Mapped[list[ArticleSource]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("project_id", "code"),
        UniqueConstraint("project_id", "doi"),
    )


class SourceRecord(Base):
    __tablename__ = "source_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    search_run_id: Mapped[str] = mapped_column(ForeignKey("search_runs.id"), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    provider_id: Mapped[str] = mapped_column(String(500))
    query_code: Mapped[str] = mapped_column(String(20))
    discovery_method: Mapped[str] = mapped_column(String(50), default="keyword")
    seed_article_id: Mapped[str | None] = mapped_column(ForeignKey("articles.id"))
    depth: Mapped[int] = mapped_column(Integer, default=0)
    raw_payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    search_run: Mapped[SearchRun] = relationship(back_populates="source_records")

    __table_args__ = (UniqueConstraint("search_run_id", "provider", "provider_id"),)


class SearchRunMetric(Base):
    __tablename__ = "search_run_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    search_run_id: Mapped[str] = mapped_column(ForeignKey("search_runs.id"), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    query_code: Mapped[str] = mapped_column(String(100))
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    records_returned: Mapped[int] = mapped_column(Integer, default=0)
    records_ingested: Mapped[int] = mapped_column(Integer, default=0)
    articles_created: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(default=False)
    last_cursor: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)

    search_run: Mapped[SearchRun] = relationship(back_populates="metrics")

    __table_args__ = (UniqueConstraint("search_run_id", "provider", "query_code"),)


class ArticleRelation(Base):
    __tablename__ = "article_relations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_article_id: Mapped[str] = mapped_column(ForeignKey("articles.id"), index=True)
    target_article_id: Mapped[str] = mapped_column(ForeignKey("articles.id"), index=True)
    relation_type: Mapped[str] = mapped_column(String(50))
    provider: Mapped[str] = mapped_column(String(50))
    confidence: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("source_article_id", "target_article_id", "relation_type"),)


class DeduplicationCandidate(Base):
    __tablename__ = "deduplication_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    article_a_id: Mapped[str] = mapped_column(ForeignKey("articles.id"), index=True)
    article_b_id: Mapped[str] = mapped_column(ForeignKey("articles.id"), index=True)
    similarity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), default="PENDING")
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("article_a_id", "article_b_id"),)


class ArticleSource(Base):
    __tablename__ = "article_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(ForeignKey("articles.id"), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    provider_id: Mapped[str] = mapped_column(String(500))
    source_record_id: Mapped[str] = mapped_column(ForeignKey("source_records.id"))

    article: Mapped[Article] = relationship(back_populates="sources")

    __table_args__ = (UniqueConstraint("article_id", "provider", "provider_id"),)


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    actor: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RepositorySource(Base):
    __tablename__ = "repository_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    domain: Mapped[str] = mapped_column(String(300))
    acquisition_method: Mapped[str] = mapped_column(String(50))
    base_url: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True)
    crawl_delay_seconds: Mapped[int] = mapped_column(Integer, default=1)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HarvestRun(Base):
    __tablename__ = "harvest_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("repository_sources.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    status: Mapped[HarvestRunStatus] = mapped_column(Enum(HarvestRunStatus))
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    records_received: Mapped[int] = mapped_column(Integer, default=0)
    records_created: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HarvestedRecord(Base):
    __tablename__ = "harvested_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("repository_sources.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(500))
    canonical_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(Text, index=True)
    abstract: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    journal: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(String(300), index=True)
    language: Mapped[str | None] = mapped_column(String(20))
    authors: Mapped[list[dict]] = mapped_column(JSON, default=list)
    external_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    document_type: Mapped[str | None] = mapped_column(String(100))
    peer_reviewed: Mapped[bool | None] = mapped_column()
    oa_locations: Mapped[list[dict]] = mapped_column(JSON, default=list)
    raw_payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("source_id", "external_id"),)


class FullTextCandidate(Base):
    __tablename__ = "fulltext_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(ForeignKey("articles.id"), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    source_url: Mapped[str] = mapped_column(Text)
    landing_page_url: Mapped[str | None] = mapped_column(Text)
    license: Mapped[str | None] = mapped_column(String(100))
    version: Mapped[str | None] = mapped_column(String(100))
    host_type: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="AVAILABLE")
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("article_id", "source_url"),)


class DownloadAttempt(Base):
    __tablename__ = "download_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("fulltext_candidates.id"), index=True)
    status: Mapped[str] = mapped_column(String(50))
    http_status: Mapped[int | None] = mapped_column(Integer)
    bytes_downloaded: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FullTextAsset(Base):
    __tablename__ = "fulltext_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(ForeignKey("articles.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("fulltext_candidates.id"), index=True)
    storage_path: Mapped[str] = mapped_column(Text, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str] = mapped_column(String(100), default="application/pdf")
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int] = mapped_column(Integer)
    license: Mapped[str | None] = mapped_column(String(100))
    source_url: Mapped[str] = mapped_column(Text)
    validation_status: Mapped[str] = mapped_column(String(50), default="VALID")
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("article_id", "sha256"),)


class PdfValidationResult(Base):
    __tablename__ = "pdf_validation_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("fulltext_assets.id"), index=True)
    signature_valid: Mapped[bool] = mapped_column(default=False)
    opens_valid: Mapped[bool] = mapped_column(default=False)
    encrypted: Mapped[bool] = mapped_column(default=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScreeningRun(Base):
    """Uma execução reproduzível de priorização/triagem de um projeto."""

    __tablename__ = "screening_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    protocol_id: Mapped[str] = mapped_column(ForeignKey("review_protocols.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    stage: Mapped[str] = mapped_column(String(50), default="SEMANTIC_PRIORITY")
    model: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(50), default="RUNNING")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    articles_processed: Mapped[int] = mapped_column(Integer, default=0)
    high_priority: Mapped[int] = mapped_column(Integer, default=0)
    medium_priority: Mapped[int] = mapped_column(Integer, default=0)
    low_priority: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScreeningDecisionRecord(Base):
    """Pontuação auditável; não representa uma exclusão humana definitiva."""

    __tablename__ = "screening_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    screening_run_id: Mapped[str] = mapped_column(ForeignKey("screening_runs.id"), index=True)
    article_id: Mapped[str] = mapped_column(ForeignKey("articles.id"), index=True)
    decision: Mapped[str] = mapped_column(String(50))
    relevance_score: Mapped[float] = mapped_column(Float)
    criteria_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list[dict]] = mapped_column(JSON, default=list)
    uncertainties: Mapped[list[str]] = mapped_column(JSON, default=list)
    exclusion_code: Mapped[str | None] = mapped_column(String(20))
    content_basis: Mapped[str] = mapped_column(String(30))
    requires_human_review: Mapped[bool] = mapped_column(default=True)
    model: Mapped[str] = mapped_column(String(300))
    prompt_version: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("screening_run_id", "article_id"),)
