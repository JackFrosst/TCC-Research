from collections.abc import Callable
from datetime import datetime, timezone
from difflib import SequenceMatcher
from time import perf_counter

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..connectors.arxiv import ArxivConnector
from ..connectors.base import AcademicConnector
from ..connectors.crossref import CrossrefConnector
from ..connectors.datacite import DataCiteConnector
from ..connectors.dblp import DblpConnector
from ..connectors.europe_pmc import EuropePmcConnector
from ..connectors.openaire import OpenAireConnector
from ..connectors.openalex import OpenAlexConnector
from ..connectors.scielo import ScieloCrossrefConnector, ScieloLocalConnector
from ..connectors.semantic_scholar import SemanticScholarConnector
from ..models import (
    Article,
    ArticleRelation,
    ArticleSource,
    DeduplicationCandidate,
    ProtocolStatus,
    ReviewProtocol,
    SearchRun,
    SearchRunMetric,
    SearchRunStatus,
    SourceRecord,
    WorkflowEvent,
)
from .normalization import (
    NormalizedRecord,
    normalize_arxiv,
    normalize_crossref,
    normalize_datacite,
    normalize_dblp,
    normalize_europe_pmc,
    normalize_manual,
    normalize_openaire,
    normalize_openalex,
    normalize_scielo,
    normalize_scielo_crossref,
    normalize_semantic_scholar,
)
from .query_compiler import compile_query


class DiscoveryError(RuntimeError):
    pass


class AcademicProviderError(DiscoveryError):
    pass


Normalizer = Callable[[dict], NormalizedRecord | None]


def connector_registry(
    settings: Settings, db: Session | None = None
) -> dict[str, tuple[AcademicConnector, Normalizer]]:
    registry = {
        "crossref": (CrossrefConnector(settings), normalize_crossref),
        "openalex": (OpenAlexConnector(settings), normalize_openalex),
        "semantic_scholar": (
            SemanticScholarConnector(settings),
            normalize_semantic_scholar,
        ),
        "dblp": (DblpConnector(settings), normalize_dblp),
        "arxiv": (ArxivConnector(settings), normalize_arxiv),
        "openaire": (OpenAireConnector(settings), normalize_openaire),
        "datacite": (DataCiteConnector(settings), normalize_datacite),
        "europe_pmc": (EuropePmcConnector(settings), normalize_europe_pmc),
        "scielo_crossref": (
            ScieloCrossrefConnector(settings),
            normalize_scielo_crossref,
        ),
    }
    if db is not None:
        registry["scielo"] = (ScieloLocalConnector(db), normalize_scielo)
    return registry


def _get_or_create_article(
    db: Session, project_id: str, record: NormalizedRecord
) -> tuple[Article, bool]:
    article = None
    if record.doi:
        article = db.scalar(
            select(Article).where(Article.project_id == project_id, Article.doi == record.doi)
        )
    if article is None:
        article = db.scalar(
            select(Article).where(
                Article.project_id == project_id,
                Article.normalized_title == record.normalized_title,
            )
        )
    if article is None:
        article = _find_fuzzy_article(db, project_id, record)
    if article is not None:
        if not article.abstract and record.abstract:
            article.abstract = record.abstract
        if not article.doi and record.doi:
            article.doi = record.doi
        article.external_ids = {**(article.external_ids or {}), **record.external_ids}
        known_urls = {item.get("pdf_url") for item in (article.oa_locations or [])}
        article.oa_locations = [
            *(article.oa_locations or []),
            *(item for item in record.oa_locations if item.get("pdf_url") not in known_urls),
        ]
        if not article.document_type and record.document_type:
            article.document_type = record.document_type
        if article.peer_reviewed is not True and record.peer_reviewed is not None:
            article.peer_reviewed = record.peer_reviewed
        return article, False

    count = db.scalar(select(func.count(Article.id)).where(Article.project_id == project_id)) or 0
    article = Article(
        project_id=project_id,
        code=f"A{count + 1:06d}",
        title=record.title,
        normalized_title=record.normalized_title,
        abstract=record.abstract,
        year=record.year,
        journal=record.journal,
        doi=record.doi,
        language=record.language,
        authors=record.authors,
        external_ids=record.external_ids,
        document_type=record.document_type,
        peer_reviewed=record.peer_reviewed,
        oa_locations=record.oa_locations,
    )
    db.add(article)
    db.flush()
    ambiguous = _find_ambiguous_article(db, project_id, record, article.id)
    if ambiguous:
        candidate, score = ambiguous
        db.add(
            DeduplicationCandidate(
                project_id=project_id,
                article_a_id=candidate.id,
                article_b_id=article.id,
                similarity=round(score * 100),
            )
        )
    return article, True


def _find_fuzzy_article(db: Session, project_id: str, record: NormalizedRecord) -> Article | None:
    title_length = len(record.normalized_title)
    prefix_expression = (
        func.left(Article.normalized_title, 16)
        if db.bind is not None and db.bind.dialect.name == "postgresql"
        else func.substr(Article.normalized_title, 1, 16)
    )
    statement = select(Article.id, Article.normalized_title, Article.authors).where(
        Article.project_id == project_id,
        prefix_expression == record.normalized_title[:16],
        func.length(Article.normalized_title).between(
            max(1, int(title_length * 0.92)), int(title_length * 1.08) + 1
        ),
    )
    if record.year:
        statement = statement.where(Article.year.between(record.year - 1, record.year + 1))
    candidates = list(db.execute(statement.limit(1000)))
    first_author = _first_author(record.authors)
    for candidate_id, candidate_title, candidate_authors in candidates:
        score = SequenceMatcher(None, candidate_title, record.normalized_title).ratio()
        if score < 0.96:
            continue
        candidate_author = _first_author(candidate_authors or [])
        if first_author and candidate_author and first_author != candidate_author:
            continue
        return db.get(Article, candidate_id)
    return None


def _first_author(authors: list[dict]) -> str | None:
    if not authors:
        return None
    value = authors[0].get("family") or authors[0].get("name")
    if not value:
        return None
    return str(value).lower().split()[-1]


def _find_ambiguous_article(
    db: Session,
    project_id: str,
    record: NormalizedRecord,
    new_article_id: str,
) -> tuple[Article, float] | None:
    title_length = len(record.normalized_title)
    prefix_expression = (
        func.left(Article.normalized_title, 16)
        if db.bind is not None and db.bind.dialect.name == "postgresql"
        else func.substr(Article.normalized_title, 1, 16)
    )
    statement = select(Article.id, Article.normalized_title, Article.authors).where(
        Article.project_id == project_id,
        Article.id != new_article_id,
        prefix_expression == record.normalized_title[:16],
        func.length(Article.normalized_title).between(
            max(1, int(title_length * 0.85)), int(title_length * 1.15) + 1
        ),
    )
    if record.year:
        statement = statement.where(Article.year.between(record.year - 1, record.year + 1))
    first_author = _first_author(record.authors)
    best: tuple[Article, float] | None = None
    for candidate_id, candidate_title, candidate_authors in db.execute(statement.limit(1000)):
        score = SequenceMatcher(None, candidate_title, record.normalized_title).ratio()
        if not 0.88 <= score < 0.96:
            continue
        candidate_author = _first_author(candidate_authors or [])
        if first_author and candidate_author and first_author != candidate_author:
            continue
        if best is None or score > best[1]:
            candidate = db.get(Article, candidate_id)
            if candidate is not None:
                best = (candidate, score)
    return best


def _ingest_record(
    db: Session,
    run: SearchRun,
    query_code: str,
    project_id: str,
    raw_record: dict,
    normalizer: Normalizer,
    discovery_method: str = "keyword",
    seed_article_id: str | None = None,
    depth: int = 0,
) -> tuple[bool, bool]:
    normalized = normalizer(raw_record)
    if normalized is None:
        return False, False
    existing = db.scalar(
        select(SourceRecord).where(
            SourceRecord.search_run_id == run.id,
            SourceRecord.provider == normalized.provider,
            SourceRecord.provider_id == normalized.provider_id,
        )
    )
    if existing:
        return False, False
    source_record = SourceRecord(
        search_run_id=run.id,
        provider=normalized.provider,
        provider_id=normalized.provider_id,
        query_code=query_code,
        discovery_method=discovery_method,
        seed_article_id=seed_article_id,
        depth=depth,
        raw_payload=raw_record,
    )
    db.add(source_record)
    db.flush()
    article, created = _get_or_create_article(db, project_id, normalized)
    relation = db.scalar(
        select(ArticleSource).where(
            ArticleSource.article_id == article.id,
            ArticleSource.provider == normalized.provider,
            ArticleSource.provider_id == normalized.provider_id,
        )
    )
    if relation is None:
        db.add(
            ArticleSource(
                article_id=article.id,
                provider=normalized.provider,
                provider_id=normalized.provider_id,
                source_record_id=source_record.id,
            )
        )
    return True, created


def run_discovery(
    db: Session,
    protocol_id: str,
    providers: list[str],
    max_results_per_provider: int,
    idempotency_key: str,
    settings: Settings,
    connectors: dict[str, tuple[AcademicConnector, Normalizer]] | None = None,
    max_total_results: int | None = None,
    resume_failed: bool = False,
    extend_completed: bool = False,
) -> SearchRun:
    previous = db.scalar(select(SearchRun).where(SearchRun.idempotency_key == idempotency_key))
    if previous:
        if previous.protocol_id != protocol_id:
            raise DiscoveryError("A chave de idempotência já pertence a outro protocolo.")
        if previous.status == SearchRunStatus.failed and not resume_failed:
            raise DiscoveryError(
                "Uma busca anterior com esta chave falhou. "
                "Envie resume_failed=true para retomar do último cursor ou use uma nova chave."
            )
        can_extend = previous.status == SearchRunStatus.completed and extend_completed
        if previous.status != SearchRunStatus.failed and not can_extend:
            return previous

    protocol = db.get(ReviewProtocol, protocol_id)
    if protocol is None:
        raise DiscoveryError("Protocolo não encontrado.")
    if protocol.status != ProtocolStatus.approved:
        raise DiscoveryError("A busca exige aprovação humana do protocolo.")
    requires_external_network = any(provider != "scielo" for provider in providers)
    if not settings.allow_live_academic_search and connectors is None and requires_external_network:
        raise DiscoveryError(
            "Busca externa desabilitada. Defina ALLOW_LIVE_ACADEMIC_SEARCH=true "
            "após revisar o protocolo."
        )

    registry = connectors or connector_registry(settings, db)
    unsupported = set(providers) - set(registry)
    if unsupported:
        raise DiscoveryError(f"Provedores não suportados: {sorted(unsupported)}")

    if previous:
        run = previous
        run.status = SearchRunStatus.running
        run.error = None
        run.finished_at = None
    else:
        run = SearchRun(
            protocol_id=protocol.id,
            idempotency_key=idempotency_key,
            providers=providers,
            status=SearchRunStatus.running,
        )
        db.add(run)
        db.flush()

    try:
        existing_metrics = list(
            db.scalars(select(SearchRunMetric).where(SearchRunMetric.search_run_id == run.id))
        )
        created_count = sum(item.articles_created for item in existing_metrics)
        received_count = sum(item.records_ingested for item in existing_metrics)
        processed_count = sum(item.records_ingested + item.duplicates for item in existing_metrics)
        total_budget = min(
            max_total_results or settings.max_total_results_per_run,
            settings.max_total_results_per_run,
        )
        for provider in providers:
            connector, normalizer = registry[provider]
            for query in protocol.queries:
                if processed_count >= total_budget:
                    break
                metric = db.scalar(
                    select(SearchRunMetric).where(
                        SearchRunMetric.search_run_id == run.id,
                        SearchRunMetric.provider == provider,
                        SearchRunMetric.query_code == query.code,
                    )
                )
                if metric and metric.completed:
                    metric_count = metric.records_ingested + metric.duplicates
                    can_continue_metric = (
                        extend_completed
                        and metric.last_cursor is not None
                        and metric_count < max_results_per_provider
                    )
                    if can_continue_metric:
                        metric.completed = False
                    else:
                        continue
                if metric is None:
                    metric = SearchRunMetric(
                        search_run_id=run.id, provider=provider, query_code=query.code
                    )
                    db.add(metric)
                    db.flush()
                metric.error = None
                started = perf_counter()
                cursor = metric.last_cursor
                per_query_count = metric.records_ingested + metric.duplicates
                while per_query_count < max_results_per_provider and processed_count < total_budget:
                    page_limit = min(
                        settings.academic_page_size,
                        max_results_per_provider - per_query_count,
                        total_budget - processed_count,
                    )
                    page = connector.search(
                        query=compile_query(provider, query.query_text),
                        year_from=protocol.year_from,
                        year_to=protocol.year_to,
                        limit=page_limit,
                        cursor=cursor,
                    )
                    metric.pages_fetched += 1
                    metric.records_returned += len(page.records)
                    if not page.records:
                        break
                    batch_limit = min(
                        len(page.records),
                        max_results_per_provider - per_query_count,
                        total_budget - processed_count,
                    )
                    for raw_record in page.records[:batch_limit]:
                        ingested, created = _ingest_record(
                            db,
                            run,
                            query.code,
                            protocol.project_id,
                            raw_record,
                            normalizer,
                        )
                        metric.records_ingested += int(ingested)
                        metric.articles_created += int(created)
                        metric.duplicates += int(not ingested)
                        received_count += int(ingested)
                        processed_count += 1
                        created_count += int(created)
                        per_query_count += 1
                    previous_cursor = cursor
                    cursor = page.next_cursor
                    metric.last_cursor = cursor
                    if not cursor or cursor == previous_cursor:
                        break
                metric.completed = True
                metric.duration_ms = int((perf_counter() - started) * 1000)
        run.records_received = received_count
        run.articles_created = created_count
        run.status = SearchRunStatus.completed
        run.finished_at = datetime.now(timezone.utc)
        db.add(
            WorkflowEvent(
                project_id=protocol.project_id,
                event_type="DISCOVERY_COMPLETED",
                actor="search-manager",
                payload={
                    "search_run_id": run.id,
                    "records_received": received_count,
                    "articles_created": created_count,
                },
            )
        )
        db.commit()
        db.refresh(run)
        return run
    except httpx.HTTPStatusError as exc:
        provider_name = locals().get("provider", "provedor acadêmico")
        detail = exc.response.text[:1000]
        run.status = SearchRunStatus.failed
        run.error = f"{provider_name}: HTTP {exc.response.status_code}: {detail}"[:4000]
        if "metric" in locals() and metric is not None:
            metric.error = run.error
            metric.duration_ms += int((perf_counter() - started) * 1000)
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise AcademicProviderError(
            f"O provedor {provider_name} rejeitou a busca (HTTP {exc.response.status_code}). "
            "Consulte os detalhes registrados na execução."
        ) from exc
    except httpx.RequestError as exc:
        provider_name = locals().get("provider", "provedor acadêmico")
        run.status = SearchRunStatus.failed
        run.error = f"{provider_name}: {exc}"[:4000]
        if "metric" in locals() and metric is not None:
            metric.error = run.error
            metric.duration_ms += int((perf_counter() - started) * 1000)
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise AcademicProviderError(
            f"Não foi possível conectar ao provedor {provider_name}."
        ) from exc
    except Exception as exc:
        error = str(exc)[:4000]
        run_id = run.id
        db.rollback()
        persisted = db.get(SearchRun, run_id)
        if persisted is None:
            persisted = SearchRun(
                id=run_id,
                protocol_id=protocol.id,
                idempotency_key=idempotency_key,
                providers=providers,
                status=SearchRunStatus.failed,
                error=error,
                finished_at=datetime.now(timezone.utc),
            )
            db.add(persisted)
        elif previous is None:
            persisted.status = SearchRunStatus.failed
            persisted.error = error
            persisted.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise


def run_manual_import(
    db: Session,
    project_id: str,
    source: str,
    records: list[dict],
    idempotency_key: str,
) -> SearchRun:
    previous = db.scalar(select(SearchRun).where(SearchRun.idempotency_key == idempotency_key))
    if previous:
        return previous
    protocol = db.scalar(
        select(ReviewProtocol)
        .where(
            ReviewProtocol.project_id == project_id,
            ReviewProtocol.status == ProtocolStatus.approved,
        )
        .order_by(ReviewProtocol.version.desc())
    )
    if protocol is None:
        raise DiscoveryError("A importação exige um protocolo aprovado para o projeto.")
    provider = f"manual_{source}"
    run = SearchRun(
        protocol_id=protocol.id,
        idempotency_key=idempotency_key,
        providers=[provider],
        status=SearchRunStatus.running,
    )
    db.add(run)
    db.flush()
    metric = SearchRunMetric(search_run_id=run.id, provider=provider, query_code="IMPORT")
    db.add(metric)
    db.flush()
    started = perf_counter()
    for item in records:
        raw = {**item, "provider": provider}
        ingested, created = _ingest_record(
            db,
            run,
            "IMPORT",
            project_id,
            raw,
            normalize_manual,
            discovery_method="manual_import",
        )
        metric.records_returned += 1
        metric.records_ingested += int(ingested)
        metric.articles_created += int(created)
        metric.duplicates += int(not ingested)
    metric.pages_fetched = 1
    metric.completed = True
    metric.duration_ms = int((perf_counter() - started) * 1000)
    run.records_received = metric.records_ingested
    run.articles_created = metric.articles_created
    run.status = SearchRunStatus.completed
    run.finished_at = datetime.now(timezone.utc)
    db.add(
        WorkflowEvent(
            project_id=project_id,
            event_type="MANUAL_IMPORT_COMPLETED",
            actor="manual-import-service",
            payload={"search_run_id": run.id, "source": source, "records": len(records)},
        )
    )
    db.commit()
    db.refresh(run)
    return run


def run_snowball(
    db: Session,
    project_id: str,
    seed_article_ids: list[str],
    providers: list[str],
    directions: list[str],
    max_results_per_seed: int,
    idempotency_key: str,
    settings: Settings,
    connectors: dict[str, tuple[AcademicConnector, Normalizer]] | None = None,
) -> SearchRun:
    previous = db.scalar(select(SearchRun).where(SearchRun.idempotency_key == idempotency_key))
    if previous:
        return previous
    if set(directions) - {"forward", "backward"}:
        raise DiscoveryError("Direções suportadas: forward e backward.")
    registry = connectors or connector_registry(settings)
    if set(providers) - {"semantic_scholar", "openalex"}:
        raise DiscoveryError("Snowballing suporta semantic_scholar e openalex.")
    protocol = db.scalar(
        select(ReviewProtocol)
        .where(
            ReviewProtocol.project_id == project_id,
            ReviewProtocol.status == ProtocolStatus.approved,
        )
        .order_by(ReviewProtocol.version.desc())
    )
    if protocol is None:
        raise DiscoveryError("Snowballing exige um protocolo aprovado.")
    seeds = list(
        db.scalars(
            select(Article).where(
                Article.project_id == project_id, Article.id.in_(seed_article_ids)
            )
        )
    )
    if len(seeds) != len(set(seed_article_ids)):
        raise DiscoveryError("Um ou mais artigos-semente não pertencem ao projeto.")
    run = SearchRun(
        protocol_id=protocol.id,
        idempotency_key=idempotency_key,
        providers=providers,
        status=SearchRunStatus.running,
    )
    db.add(run)
    db.flush()
    for seed in seeds:
        for provider in providers:
            connector, normalizer = registry[provider]
            related_method = getattr(connector, "related", None)
            if related_method is None:
                continue
            identifier = _article_identifier(seed, provider)
            if identifier is None:
                continue
            for direction in directions:
                query_code = f"{seed.code}-{direction[0].upper()}"
                metric = SearchRunMetric(
                    search_run_id=run.id,
                    provider=provider,
                    query_code=query_code,
                )
                db.add(metric)
                db.flush()
                cursor = None
                processed = 0
                started = perf_counter()
                while processed < max_results_per_seed:
                    page = related_method(
                        identifier,
                        direction,
                        min(settings.academic_page_size, max_results_per_seed - processed),
                        cursor,
                    )
                    metric.pages_fetched += 1
                    metric.records_returned += len(page.records)
                    for raw_record in page.records[: max_results_per_seed - processed]:
                        ingested, created = _ingest_record(
                            db,
                            run,
                            query_code[:20],
                            project_id,
                            raw_record,
                            normalizer,
                            discovery_method=(
                                "forward_citation"
                                if direction == "forward"
                                else "backward_reference"
                            ),
                            seed_article_id=seed.id,
                            depth=1,
                        )
                        processed += 1
                        metric.records_ingested += int(ingested)
                        metric.articles_created += int(created)
                        metric.duplicates += int(not ingested)
                        related_article = _article_for_raw(db, project_id, raw_record, normalizer)
                        if related_article and related_article.id != seed.id:
                            _save_article_relation(db, seed, related_article, direction, provider)
                    previous_cursor = cursor
                    cursor = page.next_cursor
                    metric.last_cursor = cursor
                    if not page.records or not cursor or cursor == previous_cursor:
                        break
                metric.completed = True
                metric.duration_ms = int((perf_counter() - started) * 1000)
    run.records_received = sum(metric.records_ingested for metric in run.metrics)
    run.articles_created = sum(metric.articles_created for metric in run.metrics)
    run.status = SearchRunStatus.completed
    run.finished_at = datetime.now(timezone.utc)
    db.add(
        WorkflowEvent(
            project_id=project_id,
            event_type="SNOWBALL_COMPLETED",
            actor="snowball-service",
            payload={"search_run_id": run.id, "seed_article_ids": seed_article_ids},
        )
    )
    db.commit()
    db.refresh(run)
    return run


def _article_identifier(article: Article, provider: str) -> str | None:
    if article.doi:
        return f"DOI:{article.doi}"
    if provider == "openalex":
        return (article.external_ids or {}).get("openalex")
    if provider == "semantic_scholar":
        return (article.external_ids or {}).get("semanticscholar")
    return None


def _article_for_raw(
    db: Session, project_id: str, raw_record: dict, normalizer: Normalizer
) -> Article | None:
    normalized = normalizer(raw_record)
    if normalized is None:
        return None
    if normalized.doi:
        article = db.scalar(
            select(Article).where(Article.project_id == project_id, Article.doi == normalized.doi)
        )
        if article:
            return article
    return db.scalar(
        select(Article).where(
            Article.project_id == project_id,
            Article.normalized_title == normalized.normalized_title,
        )
    )


def _save_article_relation(
    db: Session,
    seed: Article,
    related: Article,
    direction: str,
    provider: str,
) -> None:
    relation = db.scalar(
        select(ArticleRelation).where(
            ArticleRelation.source_article_id == seed.id,
            ArticleRelation.target_article_id == related.id,
            ArticleRelation.relation_type == direction,
        )
    )
    if relation is None:
        db.add(
            ArticleRelation(
                source_article_id=seed.id,
                target_article_id=related.id,
                relation_type=direction,
                provider=provider,
            )
        )
