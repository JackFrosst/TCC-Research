from __future__ import annotations

import math
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import (
    Article,
    ArticleSource,
    ProtocolStatus,
    ReviewProtocol,
    ScreeningDecisionRecord,
    ScreeningRun,
    WorkflowEvent,
)


class SemanticScreeningError(RuntimeError):
    pass


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _embed(client: httpx.Client, base_url: str, model: str, texts: list[str]) -> list[list[float]]:
    response = client.post(
        f"{base_url.rstrip('/')}/embeddings",
        json={"model": model, "input": texts},
    )
    if response.is_error:
        raise SemanticScreeningError(
            f"Servidor de embeddings respondeu HTTP {response.status_code}: {response.text[:500]}"
        )
    payload = response.json()
    ordered = sorted(payload["data"], key=lambda item: item["index"])
    return [item["embedding"] for item in ordered]


def run_semantic_screening(
    db: Session,
    *,
    project_id: str,
    idempotency_key: str,
    base_url: str,
    model: str,
    batch_size: int = 16,
    high_fraction: float = 0.05,
    medium_fraction: float = 0.15,
    timeout_seconds: float = 180.0,
    max_input_characters: int = 5_000,
    source_provider: str | None = None,
    source_provider_id_prefix: str | None = None,
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
        raise SemanticScreeningError("O projeto não possui protocolo aprovado.")

    article_query = select(Article).where(Article.project_id == project_id)
    if source_provider:
        source_article_ids = select(ArticleSource.article_id).where(
            ArticleSource.provider == source_provider
        )
        if source_provider_id_prefix:
            source_article_ids = source_article_ids.where(
                ArticleSource.provider_id.startswith(source_provider_id_prefix)
            )
        article_query = article_query.where(Article.id.in_(source_article_ids))
    articles = list(db.scalars(article_query.order_by(Article.code)))
    if not articles:
        raise SemanticScreeningError("O projeto não possui artigos.")

    criteria = {
        item.get("code", f"IC{index + 1:02d}"): item.get("text")
        or item.get("description")
        or str(item)
        for index, item in enumerate(protocol.inclusion_criteria)
    }
    if not criteria:
        raise SemanticScreeningError("O protocolo não possui critérios de inclusão.")

    run_config = {
        "base_url": base_url,
        "batch_size": batch_size,
        "high_fraction": high_fraction,
        "medium_fraction": medium_fraction,
        "protocol_version": protocol.version,
        "max_input_characters": max_input_characters,
        "source_provider": source_provider,
        "source_provider_id_prefix": source_provider_id_prefix,
        "corpus_scope": (
            f"ARTICLE_SOURCE_PROVIDER:{source_provider}"
            if source_provider
            else "ALL_PROJECT_ARTICLES"
        ),
    }
    run = existing or ScreeningRun(
        project_id=project_id,
        protocol_id=protocol.id,
        idempotency_key=idempotency_key,
        model=model,
        status="RUNNING",
        config=run_config,
    )
    # Em retomadas de uma execução falha, os parâmetros efetivamente usados
    # substituem a configuração anterior para preservar a trilha de auditoria.
    run.config = run_config
    run.status = "RUNNING"
    run.error = None
    run.finished_at = None
    db.add(run)
    db.commit()
    db.refresh(run)
    db.execute(
        delete(ScreeningDecisionRecord).where(ScreeningDecisionRecord.screening_run_id == run.id)
    )
    db.commit()

    labels = list(criteria)
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            criterion_vectors = _embed(client, base_url, model, list(criteria.values()))
            scored: list[tuple[Article, float, dict[str, float]]] = []
            for offset in range(0, len(articles), batch_size):
                batch = articles[offset : offset + batch_size]
                title_vectors = _embed(
                    client,
                    base_url,
                    model,
                    [article.title[:max_input_characters] for article in batch],
                )
                abstract_articles = [article for article in batch if article.abstract]
                abstract_vectors = (
                    _embed(
                        client,
                        base_url,
                        model,
                        [article.abstract[:max_input_characters] for article in abstract_articles],
                    )
                    if abstract_articles
                    else []
                )
                abstract_by_id = {
                    article.id: vector
                    for article, vector in zip(abstract_articles, abstract_vectors, strict=True)
                }
                for article, title_vector in zip(batch, title_vectors, strict=True):
                    scores = {
                        label: round(
                            (
                                max(
                                    _cosine(title_vector, criterion_vector),
                                    _cosine(abstract_by_id[article.id], criterion_vector)
                                    if article.id in abstract_by_id
                                    else -1.0,
                                )
                                + 1.0
                            )
                            / 2.0,
                            6,
                        )
                        for label, criterion_vector in zip(labels, criterion_vectors, strict=True)
                    }
                    # Todos os critérios são necessários; a média geométrica pune artigos
                    # que sejam fortes em apenas uma parte do protocolo.
                    relevance = math.prod(max(score, 1e-9) for score in scores.values()) ** (
                        1 / len(scores)
                    )
                    scored.append((article, relevance, scores))

        scored.sort(key=lambda item: item[1], reverse=True)
        high_end = max(1, round(len(scored) * high_fraction))
        medium_end = max(high_end + 1, round(len(scored) * (high_fraction + medium_fraction)))
        for rank, (article, relevance, scores) in enumerate(scored, start=1):
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
                    relevance_score=round(relevance, 8),
                    criteria_scores=scores,
                    content_basis="TITLE_ABSTRACT" if article.abstract else "TITLE_ONLY",
                    requires_human_review=True,
                    model=model,
                    prompt_version="semantic-priority-v1",
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
                event_type="SEMANTIC_SCREENING_COMPLETED",
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
        raise SemanticScreeningError(str(exc)) from exc
