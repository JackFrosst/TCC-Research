from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from sqlalchemy import select

from .database import SessionLocal
from .models import Article, ScreeningDecisionRecord
from .services.fulltext_screening import run_fulltext_screening


def main() -> None:
    parser = argparse.ArgumentParser(description="Triagem por texto completo com LLM local.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--base-url", default="http://host.docker.internal:8000/v1")
    parser.add_argument("--model", default="openai/gpt-oss-20b")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-articles", type=int)
    parser.add_argument("--article-ids", nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        run = run_fulltext_screening(
            db,
            project_id=args.project_id,
            source_run_id=args.source_run_id,
            idempotency_key=args.idempotency_key,
            base_url=args.base_url,
            model=args.model,
            workers=args.workers,
            max_articles=args.max_articles,
            article_ids=args.article_ids,
        )
        rows = db.execute(
            select(ScreeningDecisionRecord, Article)
            .join(Article, Article.id == ScreeningDecisionRecord.article_id)
            .where(ScreeningDecisionRecord.screening_run_id == run.id)
            .order_by(
                ScreeningDecisionRecord.decision, ScreeningDecisionRecord.relevance_score.desc()
            )
        ).all()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "article_id",
                    "code",
                    "decision",
                    "confidence",
                    "human_review",
                    "exclusion_code",
                    "doi",
                    "title",
                    "reason",
                    "criteria_and_extraction",
                    "evidence",
                    "uncertainties",
                ]
            )
            for item, article in rows:
                writer.writerow(
                    [
                        article.id,
                        article.code,
                        item.decision,
                        item.relevance_score,
                        item.requires_human_review,
                        item.exclusion_code,
                        article.doi,
                        article.title,
                        item.reason,
                        json.dumps(item.criteria_scores, ensure_ascii=False),
                        json.dumps(item.evidence, ensure_ascii=False),
                        json.dumps(item.uncertainties, ensure_ascii=False),
                    ]
                )
        print(
            f"run={run.id} processed={run.articles_processed} include={run.high_priority} "
            f"uncertain={run.medium_priority} exclude={run.low_priority} output={args.output}"
        )


if __name__ == "__main__":
    main()
