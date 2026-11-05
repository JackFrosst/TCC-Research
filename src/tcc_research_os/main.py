from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from .agents.contracts import ENABLED_AGENT_ROLES, PROHIBITED_CAPABILITIES
from .config import Settings, get_settings
from .connectors.unpaywall import UnpaywallConfigurationError
from .database import get_db
from .models import (
    Article,
    ArticleRelation,
    DeduplicationCandidate,
    FullTextCandidate,
    HarvestRun,
    Project,
    ProtocolStatus,
    RepositorySource,
    ReviewProtocol,
    ScreeningDecisionRecord,
    ScreeningRun,
    SearchRun,
    WorkflowEvent,
)
from .schemas import (
    ApprovalRequest,
    ArticleOut,
    DeduplicationDecision,
    FullTextCandidateRequest,
    HarvestRunOut,
    ManualImportRequest,
    PdfAcquisitionRequest,
    ProjectCreate,
    ProjectOut,
    ProjectSetupOut,
    ProtocolOut,
    RepositorySourceOut,
    ScieloHarvestRequest,
    SearchRequest,
    SearchRunOut,
    SnowballRequest,
)
from .services.bootstrap import bootstrap_themes
from .services.discovery import (
    AcademicProviderError,
    DiscoveryError,
    run_discovery,
    run_manual_import,
    run_snowball,
)
from .services.pdf_acquisition import (
    PdfAcquisitionError,
    acquire_pdfs,
    list_assets,
    preview_acquisition,
)
from .services.project_setup import ProjectSetupError, create_project_with_protocol
from .services.repository_harvest import HarvestError, harvest_scielo

app = FastAPI(
    title="TCC Research OS",
    version="0.2.0",
    description=(
        "Pipeline auditável para descoberta, triagem, obtenção de PDFs e leitura "
        "de literatura acadêmica. A escrita automática permanece desabilitada."
    ),
)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get("/health/live")
def live() -> dict:
    return {"status": "ok"}


@app.get("/health/ready")
def ready(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Banco indisponível") from exc
    return {"status": "ready"}


@app.get("/v1/capabilities")
def capabilities() -> dict:
    return {
        "enabled_agent_roles": sorted(ENABLED_AGENT_ROLES),
        "prohibited_capabilities": sorted(PROHIBITED_CAPABILITIES),
        "writing_enabled": False,
    }


@app.get("/v1/repositories", response_model=list[RepositorySourceOut])
def list_repositories(db: Session = Depends(get_db)) -> list[RepositorySource]:
    return list(db.scalars(select(RepositorySource).order_by(RepositorySource.slug)))


@app.post(
    "/v1/repositories/scielo/harvest",
    response_model=HarvestRunOut,
    status_code=status.HTTP_201_CREATED,
)
def collect_scielo(
    payload: ScieloHarvestRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HarvestRun:
    try:
        return harvest_scielo(
            db=db,
            settings=settings,
            collection=payload.collection,
            from_date=payload.from_date,
            until_date=payload.until_date,
            max_records=payload.max_records,
            idempotency_key=payload.idempotency_key,
        )
    except HarvestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/v1/repositories/{source_id}/harvest-runs", response_model=list[HarvestRunOut])
def list_harvest_runs(source_id: str, db: Session = Depends(get_db)) -> list[HarvestRun]:
    if db.get(RepositorySource, source_id) is None:
        raise HTTPException(status_code=404, detail="Repositório não encontrado")
    return list(
        db.scalars(
            select(HarvestRun)
            .where(HarvestRun.source_id == source_id)
            .order_by(HarvestRun.started_at.desc())
        )
    )


@app.post("/v1/bootstrap/themes", response_model=list[ProjectOut])
def create_initial_themes(db: Session = Depends(get_db)) -> list[Project]:
    return bootstrap_themes(db)


@app.post(
    "/v1/projects",
    response_model=ProjectSetupOut,
    status_code=status.HTTP_201_CREATED,
)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> dict:
    try:
        project, protocol = create_project_with_protocol(db, payload.model_dump(mode="json"))
    except ProjectSetupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"project": project, "protocol": protocol}


@app.get("/v1/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.slug)))


@app.get("/v1/projects/{project_id}/protocols", response_model=list[ProtocolOut])
def list_protocols(project_id: str, db: Session = Depends(get_db)) -> list[ReviewProtocol]:
    statement = (
        select(ReviewProtocol)
        .where(ReviewProtocol.project_id == project_id)
        .options(selectinload(ReviewProtocol.queries))
        .order_by(ReviewProtocol.version.desc())
    )
    return list(db.scalars(statement))


@app.post("/v1/protocols/{protocol_id}/approve", response_model=ProtocolOut)
def approve_protocol(
    protocol_id: str,
    payload: ApprovalRequest,
    db: Session = Depends(get_db),
) -> ReviewProtocol:
    protocol = db.scalar(
        select(ReviewProtocol)
        .where(ReviewProtocol.id == protocol_id)
        .options(selectinload(ReviewProtocol.queries))
    )
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocolo não encontrado")
    if protocol.status == ProtocolStatus.approved:
        return protocol
    protocol.status = ProtocolStatus.approved
    protocol.approved_at = datetime.now(timezone.utc)
    protocol.approved_by = payload.approved_by
    db.add(
        WorkflowEvent(
            project_id=protocol.project_id,
            event_type="PROTOCOL_APPROVED",
            actor=payload.approved_by,
            payload={"protocol_id": protocol.id, "version": protocol.version},
        )
    )
    db.commit()
    db.refresh(protocol)
    return protocol


@app.post(
    "/v1/protocols/{protocol_id}/search",
    response_model=SearchRunOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"description": "Conflito de protocolo"},
        502: {"description": "Falha de provedor acadêmico"},
    },
)
def search_protocol(
    protocol_id: str,
    payload: SearchRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        return run_discovery(
            db=db,
            protocol_id=protocol_id,
            providers=[provider.value for provider in payload.providers],
            max_results_per_provider=min(
                payload.max_results_per_provider or payload.max_results_per_query,
                settings.max_results_per_query,
            ),
            idempotency_key=payload.idempotency_key,
            settings=settings,
            max_total_results=min(payload.max_total_results, settings.max_total_results_per_run),
            resume_failed=payload.resume_failed,
            extend_completed=payload.extend_completed,
        )
    except AcademicProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except DiscoveryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/v1/search-runs/{run_id}", response_model=SearchRunOut)
def get_search_run(run_id: str, db: Session = Depends(get_db)) -> SearchRun:
    run = db.scalar(
        select(SearchRun).where(SearchRun.id == run_id).options(selectinload(SearchRun.metrics))
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Execução não encontrada")
    return run


@app.post("/v1/projects/{project_id}/snowball", response_model=SearchRunOut)
def snowball_project(
    project_id: str,
    payload: SnowballRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SearchRun:
    try:
        return run_snowball(
            db=db,
            project_id=project_id,
            seed_article_ids=payload.seed_article_ids,
            providers=[provider.value for provider in payload.providers],
            directions=payload.directions,
            max_results_per_seed=payload.max_results_per_seed,
            idempotency_key=payload.idempotency_key,
            settings=settings,
        )
    except (AcademicProviderError, DiscoveryError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/projects/{project_id}/imports", response_model=SearchRunOut)
def import_project_records(
    project_id: str,
    payload: ManualImportRequest,
    db: Session = Depends(get_db),
) -> SearchRun:
    try:
        return run_manual_import(
            db,
            project_id,
            payload.source,
            [record.model_dump(mode="json") for record in payload.records],
            payload.idempotency_key,
        )
    except DiscoveryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/v1/projects/{project_id}/articles", response_model=list[ArticleOut])
def list_articles(project_id: str, db: Session = Depends(get_db)) -> list[Article]:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    statement = (
        select(Article)
        .where(Article.project_id == project_id)
        .options(selectinload(Article.sources))
        .order_by(Article.code)
    )
    return list(db.scalars(statement))


@app.get("/v1/projects/{project_id}/deduplication-candidates")
def list_deduplication_candidates(project_id: str, db: Session = Depends(get_db)) -> list[dict]:
    candidates = list(
        db.scalars(
            select(DeduplicationCandidate)
            .where(DeduplicationCandidate.project_id == project_id)
            .order_by(DeduplicationCandidate.created_at)
        )
    )
    items = []
    for candidate in candidates:
        article_a = db.get(Article, candidate.article_a_id)
        article_b = db.get(Article, candidate.article_b_id)
        items.append(
            {
                "id": candidate.id,
                "similarity": candidate.similarity,
                "status": candidate.status,
                "article_a": {"id": article_a.id, "title": article_a.title},
                "article_b": {"id": article_b.id, "title": article_b.title},
            }
        )
    return items


@app.post("/v1/deduplication-candidates/{candidate_id}/decide")
def decide_deduplication_candidate(
    candidate_id: str,
    payload: DeduplicationDecision,
    db: Session = Depends(get_db),
) -> dict:
    candidate = db.get(DeduplicationCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidato não encontrado")
    if candidate.status != "PENDING":
        return {"id": candidate.id, "status": candidate.status}
    candidate.status = payload.decision.upper()
    candidate.decided_by = payload.decided_by
    candidate.decided_at = datetime.now(timezone.utc)
    if payload.decision in {"same_work", "version_of"}:
        db.add(
            ArticleRelation(
                source_article_id=candidate.article_a_id,
                target_article_id=candidate.article_b_id,
                relation_type=payload.decision,
                provider="human_review",
                confidence=100,
            )
        )
    db.add(
        WorkflowEvent(
            project_id=candidate.project_id,
            event_type="DEDUPLICATION_DECIDED",
            actor=payload.decided_by,
            payload={"candidate_id": candidate.id, "decision": payload.decision},
        )
    )
    db.commit()
    return {"id": candidate.id, "status": candidate.status}


@app.post("/v1/projects/{project_id}/pdf-acquisitions/preview")
def preview_project_pdfs(
    project_id: str,
    payload: PdfAcquisitionRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        return preview_acquisition(
            db=db,
            project_id=project_id,
            max_articles=payload.max_articles,
            require_known_license=payload.require_known_license,
            settings=settings,
            article_ids=payload.article_ids,
        )
    except (PdfAcquisitionError, UnpaywallConfigurationError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/projects/{project_id}/pdf-acquisitions")
def download_project_pdfs(
    project_id: str,
    payload: PdfAcquisitionRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        return acquire_pdfs(
            db=db,
            project_id=project_id,
            max_articles=payload.max_articles,
            require_known_license=payload.require_known_license,
            settings=settings,
            article_ids=payload.article_ids,
        )
    except (PdfAcquisitionError, UnpaywallConfigurationError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/v1/projects/{project_id}/pdf-acquisitions")
def list_project_pdfs(project_id: str, db: Session = Depends(get_db)) -> list[dict]:
    return list_assets(db, project_id)


@app.get("/v1/articles/{article_id}/fulltext")
def article_fulltext(article_id: str, db: Session = Depends(get_db)) -> dict:
    article = db.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Artigo não encontrado")
    assets = [
        item for item in list_assets(db, article.project_id) if item["article_id"] == article_id
    ]
    return {"article_id": article.id, "assets": assets}


@app.get("/v1/projects/{project_id}/screening-runs")
def list_screening_runs(project_id: str, db: Session = Depends(get_db)) -> list[dict]:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    runs = db.scalars(
        select(ScreeningRun)
        .where(ScreeningRun.project_id == project_id)
        .order_by(ScreeningRun.started_at.desc())
    )
    return [
        {
            "id": run.id,
            "stage": run.stage,
            "model": run.model,
            "status": run.status,
            "articles_processed": run.articles_processed,
            "high_priority": run.high_priority,
            "medium_priority": run.medium_priority,
            "low_priority": run.low_priority,
            "config": run.config,
            "error": run.error,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }
        for run in runs
    ]


@app.get("/v1/screening-runs/{run_id}/decisions")
def list_screening_decisions(
    run_id: str,
    decision: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[dict]:
    if db.get(ScreeningRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Execução de triagem não encontrada")
    statement = (
        select(ScreeningDecisionRecord, Article)
        .join(Article, Article.id == ScreeningDecisionRecord.article_id)
        .where(ScreeningDecisionRecord.screening_run_id == run_id)
    )
    if decision:
        statement = statement.where(ScreeningDecisionRecord.decision == decision.upper())
    rows = db.execute(
        statement.order_by(ScreeningDecisionRecord.relevance_score.desc())
        .offset(max(offset, 0))
        .limit(min(max(limit, 1), 1000))
    ).all()
    return [
        {
            "article_id": article.id,
            "code": article.code,
            "title": article.title,
            "abstract": article.abstract,
            "year": article.year,
            "doi": article.doi,
            "decision": item.decision,
            "relevance_score": item.relevance_score,
            "criteria_scores": item.criteria_scores,
            "reason": item.reason,
            "evidence": item.evidence,
            "uncertainties": item.uncertainties,
            "exclusion_code": item.exclusion_code,
            "content_basis": item.content_basis,
            "requires_human_review": item.requires_human_review,
        }
        for item, article in rows
    ]


@app.post("/v1/articles/{article_id}/fulltext-candidates", status_code=201)
def register_fulltext_candidate(
    article_id: str,
    payload: FullTextCandidateRequest,
    db: Session = Depends(get_db),
) -> dict:
    article = db.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Artigo não encontrado")
    existing = db.scalar(
        select(FullTextCandidate).where(
            FullTextCandidate.article_id == article_id,
            FullTextCandidate.source_url == payload.source_url,
        )
    )
    candidate = existing or FullTextCandidate(
        article_id=article_id,
        provider=payload.provider,
        source_url=payload.source_url,
        landing_page_url=payload.landing_page_url,
        license=payload.license,
        version=payload.version,
        host_type="manual",
        status="LICENSE_REVIEW_REQUIRED" if not payload.license else "AVAILABLE",
        raw_payload={"registered_manually": True},
    )
    db.add(candidate)
    db.add(
        WorkflowEvent(
            project_id=article.project_id,
            event_type="FULLTEXT_CANDIDATE_REGISTERED",
            actor="human",
            payload={"article_id": article.id, "source_url": payload.source_url},
        )
    )
    db.commit()
    db.refresh(candidate)
    return {"id": candidate.id, "status": candidate.status, "provider": candidate.provider}
