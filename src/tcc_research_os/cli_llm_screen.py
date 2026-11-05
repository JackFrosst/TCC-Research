from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from sqlalchemy import select

from .database import SessionLocal
from .models import Article, ScreeningDecisionRecord
from .services.llm_screening import run_llm_screening


def main() -> None:
    parser = argparse.ArgumentParser(description="Triagem generativa local de titulo e resumo.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--base-url", default="http://host.docker.internal:8103/v1")
    parser.add_argument("--model", default="openai/gpt-oss-20b")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with SessionLocal() as db:
        run = run_llm_screening(
            db,
            project_id=args.project_id,
            source_run_id=args.source_run_id,
            idempotency_key=args.idempotency_key,
            base_url=args.base_url,
            model=args.model,
            workers=args.workers,
        )
        rows = db.execute(
            select(ScreeningDecisionRecord, Article)
            .join(Article, Article.id == ScreeningDecisionRecord.article_id)
            .where(ScreeningDecisionRecord.screening_run_id == run.id)
            .order_by(
                ScreeningDecisionRecord.decision,
                ScreeningDecisionRecord.relevance_score.desc(),
            )
        ).all()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        header = [
            "article_id", "code", "decision", "confidence", "human_review",
            "exclusion_code", "year", "doi", "title", "abstract", "reason",
            "criteria", "evidence", "uncertainties",
        ]

        def serialize(item, article) -> list:
            return [
                article.id, article.code, item.decision, item.relevance_score,
                item.requires_human_review, item.exclusion_code, article.year, article.doi,
                article.title, article.abstract, item.reason,
                json.dumps(item.criteria_scores, ensure_ascii=False, sort_keys=True),
                json.dumps(item.evidence, ensure_ascii=False),
                json.dumps(item.uncertainties, ensure_ascii=False),
            ]

        with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for item, article in rows:
                writer.writerow(serialize(item, article))

        included_output = args.output.with_name(f"{args.output.stem}-incluidos.csv")
        with included_output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for item, article in rows:
                if item.decision == "INCLUDE":
                    writer.writerow(serialize(item, article))
        print(
            f"run={run.id} processed={run.articles_processed} include={run.high_priority} "
            f"uncertain={run.medium_priority} exclude={run.low_priority} output={args.output} "
            f"included_output={included_output}"
        )


if __name__ == "__main__":
    main()
