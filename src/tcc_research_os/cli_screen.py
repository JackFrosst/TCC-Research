from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from sqlalchemy import select

from .database import SessionLocal
from .models import Article, ScreeningDecisionRecord
from .services.semantic_screening import run_semantic_screening


def main() -> None:
    parser = argparse.ArgumentParser(description="Prioriza artigos usando embeddings locais.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--base-url", default="http://host.docker.internal:8101/v1")
    parser.add_argument("--model", default="Qwen/Qwen3-Embedding-4B")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument(
        "--max-input-characters",
        type=int,
        default=5_000,
        help="Limite conservador por título/resumo para modelos com janela de 4096 tokens.",
    )
    parser.add_argument("--source-provider")
    parser.add_argument("--source-provider-id-prefix")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    with SessionLocal() as db:
        run = run_semantic_screening(
            db,
            project_id=args.project_id,
            idempotency_key=args.idempotency_key,
            base_url=args.base_url,
            model=args.model,
            batch_size=args.batch_size,
            max_input_characters=args.max_input_characters,
            source_provider=args.source_provider,
            source_provider_id_prefix=args.source_provider_id_prefix,
        )
        output = args.output or Path("storage") / f"screening-{run.id}.csv"
        output.parent.mkdir(parents=True, exist_ok=True)
        rows = db.execute(
            select(ScreeningDecisionRecord, Article)
            .join(Article, Article.id == ScreeningDecisionRecord.article_id)
            .where(ScreeningDecisionRecord.screening_run_id == run.id)
            .order_by(ScreeningDecisionRecord.relevance_score.desc())
        ).all()
        header = [
            "rank",
            "article_id",
            "code",
            "decision",
            "score",
            "content_basis",
            "year",
            "doi",
            "title",
            "abstract",
            "criteria_scores",
        ]

        def serialize(rank: int, decision, article) -> list:
            return [
                rank,
                article.id,
                article.code,
                decision.decision,
                decision.relevance_score,
                decision.content_basis,
                article.year,
                article.doi,
                article.title,
                article.abstract,
                json.dumps(decision.criteria_scores, ensure_ascii=False, sort_keys=True),
            ]

        with output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for rank, (decision, article) in enumerate(rows, start=1):
                writer.writerow(serialize(rank, decision, article))

        evidence_output = output.with_name(f"{output.stem}-principais-com-resumo.csv")
        evidence_rows = [row for row in rows if row[1].abstract][:300]
        with evidence_output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for rank, (decision, article) in enumerate(evidence_rows, start=1):
                writer.writerow(serialize(rank, decision, article))
        print(
            f"run={run.id} processed={run.articles_processed} high={run.high_priority} "
            f"medium={run.medium_priority} low={run.low_priority} output={output} "
            f"evidence_output={evidence_output}"
        )


if __name__ == "__main__":
    main()
