from __future__ import annotations

import html
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Article,
    ProtocolStatus,
    ReviewProtocol,
    ScreeningDecisionRecord,
    ScreeningRun,
    WorkflowEvent,
)


class RerankingError(RuntimeError):
    pass


def _review_query(protocol: ReviewProtocol) -> str:
    inclusion = "; ".join(
        str(item.get("text") or item.get("description") or item)
        for item in protocol.inclusion_criteria
    )
    exclusion = "; ".join(
        str(item.get("text") or item.get("description") or item)
        for item in protocol.exclusion_criteria
    )
    return (
        f"Pergunta da revisão: {protocol.research_question} "
        f"Critérios necessários de inclusão: {inclusion}. "
        f"Critérios de exclusão: {exclusion}. "
        "Priorize estudos acadêmicos técnicos ou empíricos que respondam diretamente à pergunta, "
        "apresentem arquitetura, protocolo, experimento ou métricas, e não apenas menções "
        "genéricas."
    )


_PROMPT_CONTAMINATION = re.compile(
    r"\b(the user wants me|let me analyze|allowed citation keys|verification results|"
    r"remove all ai writing|as an ai language model)\b",
    re.IGNORECASE,
)


def _clean_document(article: Article) -> tuple[str, str]:
    title = re.sub(r"\s+", " ", html.unescape(article.title)).strip()
    if len(title) > 1_000:
        return title[:1_000], "MALFORMED_TITLE"
    abstract = re.sub(r"<[^>]+>", " ", html.unescape(article.abstract or ""))
    abstract = re.sub(r"\s+", " ", abstract).strip()
    if len(abstract) > 12_000 or _PROMPT_CONTAMINATION.search(abstract):
        abstract = ""
        quality = "ABSTRACT_REJECTED"
    else:
        quality = "TITLE_ABSTRACT" if abstract else "TITLE_ONLY"
    document = f"Title: {title}"
    if abstract:
        document += f"\nAbstract: {abstract[:6_000]}"
    return document, quality


def _rerank(
    client: httpx.Client,
    *,
    base_url: str,
    model: str,
    query: str,
    documents: list[str],
) -> list[float]:
    response = client.post(
        f"{base_url.rstrip('/')}/rerank",
        json={"model": model, "query": query, "documents": documents, "top_n": len(documents)},
    )
    if response.is_error:
        raise RerankingError(
            f"Servidor de reranking respondeu HTTP {response.status_code}: {response.text[:500]}"
        )
    scores = [0.0] * len(documents)
    for item in response.json()["results"]:
        scores[item["index"]] = float(item["relevance_score"])
    return scores


def run_reranking(
    db: Session,
    *,
    project_id: str,
    idempotency_key: str,
    base_url: str,
    model: str,
    source_run_id: str | None = None,
    batch_size: int = 16,
    high_fraction: float = 0.05,
    medium_fraction: float = 0.15,
    timeout_seconds: float = 180.0,
    max_input_characters: int = 5_000,
) -> ScreeningRun:
    existing = db.scalar(
        select(ScreeningRun).where(ScreeningRun.idempotency_key == idempotency_key)
    )
    if existing is not None and existing.status == "COMPLETED":
        return existing

    protocol = db.scalar(
        select(ReviewProtocol)
        .where(
            ReviewProtocol.project_id == project_id,
            ReviewProtocol.status == ProtocolStatus.approved,
        )
        .order_by(ReviewProtocol.version.desc())
    )
    if protocol is None:
        raise RerankingError("O projeto não possui protocolo aprovado.")
    source_scores: dict[str, tuple[float, int]] = {}
    if source_run_id:
        source_run = db.get(ScreeningRun, source_run_id)
        if source_run is None or source_run.project_id != project_id:
            raise RerankingError("Execução semântica de origem não encontrada no projeto.")
        source_rows = db.execute(
            select(ScreeningDecisionRecord, Article)
            .join(Article, Article.id == ScreeningDecisionRecord.article_id)
            .where(
                ScreeningDecisionRecord.screening_run_id == source_run_id,
                ScreeningDecisionRecord.decision.in_(["PRIORITY_HIGH", "PRIORITY_MEDIUM"]),
            )
            .order_by(ScreeningDecisionRecord.relevance_score.desc())
        ).all()
        articles = [article for _, article in source_rows]
        source_scores = {
            article.id: (item.relevance_score, rank)
            for rank, (item, article) in enumerate(source_rows, start=1)
        }
    else:
        articles = list(
            db.scalars(
                select(Article).where(Article.project_id == project_id).order_by(Article.code)
            )
        )
    if not articles:
        raise RerankingError("O projeto não possui artigos.")

    run = existing or ScreeningRun(
        project_id=project_id,
        protocol_id=protocol.id,
        idempotency_key=idempotency_key,
        stage="RERANKING",
        model=model,
        status="RUNNING",
        config={
            "base_url": base_url,
            "batch_size": batch_size,
            "high_fraction": high_fraction,
            "medium_fraction": medium_fraction,
            "protocol_version": protocol.version,
            "max_input_characters": max_input_characters,
            "corpus_scope": (
                "SEMANTIC_HIGH_MEDIUM" if source_run_id else "ALL_PROJECT_ARTICLES"
            ),
            "source_run_id": source_run_id,
            "fusion": "weighted_reciprocal_rank_0.65_semantic_0.35_reranker",
        },
    )
    run.status = "RUNNING"
    run.error = None
    run.finished_at = None
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        query = _review_query(protocol)
        raw_scored: list[tuple[Article, float, str]] = []
        with httpx.Client(timeout=timeout_seconds) as client:
            for offset in range(0, len(articles), batch_size):
                batch = articles[offset : offset + batch_size]
                cleaned = [_clean_document(article) for article in batch]
                documents = [document[:max_input_characters] for document, _ in cleaned]
                scores = _rerank(
                    client,
                    base_url=base_url,
                    model=model,
                    query=query,
                    documents=documents,
                )
                raw_scored.extend(
                    (article, score, quality)
                    for article, score, (_, quality) in zip(batch, scores, cleaned, strict=True)
                )

        reranker_order = sorted(raw_scored, key=lambda item: item[1], reverse=True)
        reranker_ranks = {
            article.id: rank for rank, (article, _, _) in enumerate(reranker_order, start=1)
        }
        if source_run_id:
            scored = [
                (
                    article,
                    0.65 / (60 + source_scores[article.id][1])
                    + 0.35 / (60 + reranker_ranks[article.id]),
                    quality,
                    raw_score,
                )
                for article, raw_score, quality in raw_scored
            ]
        else:
            scored = [
                (article, raw_score, quality, raw_score)
                for article, raw_score, quality in raw_scored
            ]
        scored.sort(key=lambda item: item[1], reverse=True)
        high_end = max(1, round(len(scored) * high_fraction))
        medium_end = max(high_end + 1, round(len(scored) * (high_fraction + medium_fraction)))
        for rank, (article, score, quality, raw_score) in enumerate(scored, start=1):
            decision = (
                "PRIORITY_HIGH"
                if rank <= high_end
                else "PRIORITY_MEDIUM"
                if rank <= medium_end
                else "PRIORITY_LOW"
            )
            db.add(
                ScreeningDecisionRecord(
                    screening_run_id=run.id,
                    article_id=article.id,
                    decision=decision,
                    relevance_score=round(score, 8),
                    criteria_scores={
                        "fusion_score": round(score, 8),
                        "raw_reranker": round(raw_score, 8),
                        "metadata_quality": quality,
                        "source_semantic": (
                            round(source_scores[article.id][0], 8) if source_run_id else None
                        ),
                        "semantic_rank": (
                            source_scores[article.id][1] if source_run_id else None
                        ),
                        "reranker_rank": reranker_ranks[article.id],
                    },
                    content_basis=(
                        "TITLE_ABSTRACT" if quality == "TITLE_ABSTRACT" else "TITLE_ONLY"
                    ),
                    requires_human_review=True,
                    model=model,
                    prompt_version="protocol-reranker-fusion-v2",
                )
            )
            if rank % 1000 == 0:
                db.commit()
        db.commit()

        run.status = "COMPLETED"
        run.articles_processed = len(scored)
        run.high_priority = high_end
        run.medium_priority = medium_end - high_end
        run.low_priority = len(scored) - medium_end
        run.finished_at = datetime.now(timezone.utc)
        db.add(
            WorkflowEvent(
                project_id=project_id,
                event_type="RERANKING_COMPLETED",
                actor=model,
                payload={"screening_run_id": run.id, "articles_processed": len(scored)},
            )
        )
        db.commit()
        db.refresh(run)
        return run
    except Exception as exc:
        db.rollback()
        run.status = "FAILED"
        run.error = str(exc)
        run.finished_at = datetime.now(timezone.utc)
        db.add(run)
        db.commit()
        raise RerankingError(str(exc)) from exc
