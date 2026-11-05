from __future__ import annotations

import argparse
import csv
from pathlib import Path

from sqlalchemy import select

from .database import SessionLocal
from .models import Article, ArticleSource, FullTextAsset, ScreeningDecisionRecord


def _quality_status(article: Article) -> tuple[str, list[str]]:
    flags: list[str] = []
    document_type = (article.document_type or "").lower()
    journal = (article.journal or "").lower()
    doi = (article.doi or "").lower()
    if article.peer_reviewed is True:
        return "PEER_REVIEWED_CONFIRMED", flags
    if article.peer_reviewed is False:
        flags.append("PEER_REVIEWED_FALSE_IN_METADATA")
    if doi.startswith("10.5281/zenodo.") or "zenodo" in journal:
        flags.extend(["ZENODO_DEPOSIT", "PEER_REVIEW_NOT_ESTABLISHED"])
        return "GREY_LITERATURE", flags
    if document_type in {"preprint", "report", "text"}:
        flags.extend(["NON_JOURNAL_DOCUMENT", "PEER_REVIEW_NOT_ESTABLISHED"])
        return "GREY_LITERATURE", flags
    if article.journal and article.doi:
        flags.append("PEER_REVIEW_REQUIRES_EDITORIAL_VERIFICATION")
        return "LIKELY_SCHOLARLY_VERIFY", flags
    flags.append("INSUFFICIENT_PROVENANCE_METADATA")
    return "PROVENANCE_REVIEW", flags


def main() -> None:
    parser = argparse.ArgumentParser(description="Relatorio de qualidade dos artigos triados.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--decision", default="INCLUDE")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with SessionLocal() as db:
        rows = db.execute(
            select(ScreeningDecisionRecord, Article)
            .join(Article, Article.id == ScreeningDecisionRecord.article_id)
            .where(
                ScreeningDecisionRecord.screening_run_id == args.run_id,
                ScreeningDecisionRecord.decision == args.decision.upper(),
            )
            .order_by(ScreeningDecisionRecord.relevance_score.desc())
        ).all()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        counts: dict[str, int] = {}
        with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "article_id", "code", "quality_status", "quality_flags", "confidence",
                    "year", "document_type", "peer_reviewed", "journal", "doi", "providers",
                    "pdf_downloaded", "pdf_pages", "pdf_license", "title",
                ]
            )
            for decision, article in rows:
                status, flags = _quality_status(article)
                counts[status] = counts.get(status, 0) + 1
                providers = sorted(
                    set(
                        db.scalars(
                            select(ArticleSource.provider).where(
                                ArticleSource.article_id == article.id
                            )
                        )
                    )
                )
                asset = db.scalar(
                    select(FullTextAsset).where(FullTextAsset.article_id == article.id)
                )
                writer.writerow(
                    [
                        article.id, article.code, status, ";".join(flags),
                        decision.relevance_score, article.year, article.document_type,
                        article.peer_reviewed, article.journal, article.doi, ";".join(providers),
                        bool(asset), asset.page_count if asset else None,
                        asset.license if asset else None, article.title,
                    ]
                )
        print(" ".join(f"{key}={value}" for key, value in sorted(counts.items())))
        print(f"output={args.output}")


if __name__ == "__main__":
    main()
