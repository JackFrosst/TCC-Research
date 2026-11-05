from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from sqlalchemy import select

from .database import SessionLocal
from .models import Article, ScreeningDecisionRecord
from .services.reranking import run_reranking


def main() -> None:
    parser = argparse.ArgumentParser(description="Reordena artigos com reranker local.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--base-url", default="http://host.docker.internal:8102/v1")
    parser.add_argument("--model", default="Qwen/Qwen3-Reranker-4B")
    parser.add_argument("--source-run-id")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-input-characters", type=int, default=5_000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with SessionLocal() as db:
        run = run_reranking(
            db,
            project_id=args.project_id,
            idempotency_key=args.idempotency_key,
            base_url=args.base_url,
            model=args.model,
            source_run_id=args.source_run_id,
            batch_size=args.batch_size,
            max_input_characters=args.max_input_characters,
        )
        rows = db.execute(
            select(ScreeningDecisionRecord, Article)
            .join(Article, Article.id == ScreeningDecisionRecord.article_id)
            .where(ScreeningDecisionRecord.screening_run_id == run.id)
            .order_by(ScreeningDecisionRecord.relevance_score.desc())
        ).all()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        header = [
            "rank",
            "article_id",
            "code",
            "decision",
            "reranker_score",
            "content_basis",
            "year",
            "doi",
            "title",
            "abstract",
            "scores",
        ]

        def serialize(rank: int, item, article) -> list:
            return [
                rank,
                article.id,
                article.code,
                item.decision,
                item.relevance_score,
                item.content_basis,
                article.year,
                article.doi,
                article.title,
                article.abstract,
                json.dumps(item.criteria_scores, ensure_ascii=False, sort_keys=True),
            ]

        with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for rank, (item, article) in enumerate(rows, start=1):
                writer.writerow(serialize(rank, item, article))

        evidence_output = args.output.with_name(f"{args.output.stem}-principais-com-resumo.csv")
        evidence_rows = [row for row in rows if row[1].abstract][:300]
        with evidence_output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for rank, (item, article) in enumerate(evidence_rows, start=1):
                writer.writerow(serialize(rank, item, article))

        print(
            f"run={run.id} processed={run.articles_processed} high={run.high_priority} "
            f"medium={run.medium_priority} low={run.low_priority} output={args.output} "
            f"evidence_output={evidence_output}"
        )


if __name__ == "__main__":
    main()
