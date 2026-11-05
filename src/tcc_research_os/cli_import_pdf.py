from __future__ import annotations

import argparse
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select

from .config import get_settings
from .database import SessionLocal
from .models import (
    Article,
    FullTextAsset,
    FullTextCandidate,
    PdfValidationResult,
    Project,
    WorkflowEvent,
)
from .services.pdf_acquisition import _destination, _write_manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Importa um PDF obtido manualmente de uma fonte publica."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--article-id", required=True)
    parser.add_argument("--source-file", required=True, type=Path)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--license", required=True)
    parser.add_argument("--provider", default="manual_browser")
    parser.add_argument("--version", default="publishedVersion")
    args = parser.parse_args()

    settings = get_settings()
    source = args.source_file.resolve()
    if not source.is_file():
        raise SystemExit(f"Arquivo nao encontrado: {source}")
    if source.stat().st_size > settings.max_pdf_size_mb * 1024 * 1024:
        raise SystemExit("O PDF excede o limite configurado.")
    with source.open("rb") as handle:
        signature = handle.read(5)
    if signature != b"%PDF-":
        raise SystemExit("O arquivo nao possui assinatura PDF.")
    reader = PdfReader(source)
    if reader.is_encrypted:
        raise SystemExit("PDF criptografado nao pode entrar no corpus.")
    page_count = len(reader.pages)
    if page_count < 1:
        raise SystemExit("O PDF nao contem paginas legiveis.")
    with source.open("rb") as handle:
        sha256 = hashlib.file_digest(handle, "sha256").hexdigest()

    with SessionLocal() as db:
        project = db.get(Project, args.project_id)
        article = db.get(Article, args.article_id)
        if project is None or article is None or article.project_id != project.id:
            raise SystemExit("Projeto ou artigo invalido.")
        existing_asset = db.scalar(
            select(FullTextAsset).where(FullTextAsset.article_id == article.id)
        )
        if existing_asset:
            print(f"already_imported asset_id={existing_asset.id}")
            return

        candidate = db.scalar(
            select(FullTextCandidate).where(
                FullTextCandidate.article_id == article.id,
                FullTextCandidate.source_url == args.source_url,
            )
        )
        if candidate is None:
            candidate = FullTextCandidate(
                article_id=article.id,
                provider=args.provider,
                source_url=args.source_url,
                landing_page_url=None,
                license=args.license,
                version=args.version,
                host_type="manual",
                status="AVAILABLE",
                raw_payload={"imported_from_local_file": True},
            )
            db.add(candidate)
            db.flush()

        destination = _destination(settings, project.slug, article)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".pdf.part")
        shutil.copyfile(source, temporary)
        temporary.replace(destination)
        asset = FullTextAsset(
            article_id=article.id,
            candidate_id=candidate.id,
            storage_path=str(destination),
            sha256=sha256,
            mime_type="application/pdf",
            file_size_bytes=destination.stat().st_size,
            page_count=page_count,
            license=args.license,
            source_url=args.source_url,
            validation_status="VALID",
        )
        db.add(asset)
        db.flush()
        db.add(
            PdfValidationResult(
                asset_id=asset.id,
                signature_valid=True,
                opens_valid=True,
                encrypted=False,
                page_count=page_count,
                warnings=["Imported from a browser download after publisher anti-bot validation."],
            )
        )
        candidate.status = "DOWNLOADED"
        db.add(
            WorkflowEvent(
                project_id=project.id,
                event_type="PDF_MANUALLY_IMPORTED",
                actor="human-assisted-browser",
                payload={
                    "article_id": article.id,
                    "source_url": args.source_url,
                    "sha256": sha256,
                    "imported_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        )
        db.commit()
        _write_manifest(db, project, settings)
        print(
            f"imported asset_id={asset.id} code={article.code} pages={page_count} "
            f"sha256={sha256} path={destination}"
        )


if __name__ == "__main__":
    main()
