import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..connectors.unpaywall import OpenAccessLocation, UnpaywallConnector
from ..connectors.zenodo import ZenodoConnector
from ..models import (
    Article,
    DownloadAttempt,
    FullTextAsset,
    FullTextCandidate,
    PdfValidationResult,
    Project,
    WorkflowEvent,
)
from .pdf_downloader import SafePdfDownloader


class PdfAcquisitionError(RuntimeError):
    pass


def preview_acquisition(
    db: Session,
    project_id: str,
    max_articles: int,
    require_known_license: bool,
    settings: Settings,
    connector: UnpaywallConnector | None = None,
    zenodo_connector: ZenodoConnector | None = None,
    article_ids: list[str] | None = None,
) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise PdfAcquisitionError("Projeto não encontrado.")
    service = connector
    statement = select(Article).where(Article.project_id == project_id)
    if article_ids:
        statement = statement.where(Article.id.in_(article_ids))
    statement = statement.order_by(Article.code).limit(max_articles)
    articles = list(db.scalars(statement))
    items: list[dict] = []
    counts = {
        "articles_checked": 0,
        "oa_pdf_available": 0,
        "eligible_for_download": 0,
        "missing_pdf": 0,
        "missing_known_license": 0,
        "already_downloaded": 0,
        "lookup_errors": 0,
    }
    for article in articles:
        counts["articles_checked"] += 1
        existing_asset = db.scalar(
            select(FullTextAsset).where(FullTextAsset.article_id == article.id)
        )
        if existing_asset:
            counts["already_downloaded"] += 1
            items.append(_preview_item(article, "ALREADY_DOWNLOADED", None, existing_asset.id))
            continue
        # Candidates explicitly registered or previously resolved are part of the
        # acquisition queue.  Without loading them here, the manual registration
        # endpoint persisted a URL that preview/acquire could never consume.
        locations = _stored_candidate_locations(db, article.id)
        known_urls = {item.pdf_url for item in locations}
        locations.extend(
            item
            for item in _embedded_locations(article)
            if item.pdf_url not in known_urls
        )
        if article.doi and not locations and ZenodoConnector.doi_pattern.fullmatch(article.doi):
            try:
                zenodo = zenodo_connector or ZenodoConnector(settings)
                location = zenodo.find_pdf(article.doi)
                if location:
                    locations.append(location)
            except Exception as exc:
                counts["lookup_errors"] += 1
                items.append(_preview_item(article, "LOOKUP_ERROR", None, error=str(exc)))
                continue
        needs_unpaywall = article.doi and (
            not locations or (require_known_license and not any(item.license for item in locations))
        )
        if needs_unpaywall:
            try:
                service = service or UnpaywallConnector(settings)
                location = service.find_pdf(article.doi)
                if location:
                    locations.append(location)
            except Exception as exc:
                counts["lookup_errors"] += 1
                if not locations:
                    items.append(_preview_item(article, "LOOKUP_ERROR", None, error=str(exc)))
                    continue
        if not locations:
            counts["missing_pdf"] += 1
            items.append(_preview_item(article, "NO_OA_PDF", None))
            continue
        counts["oa_pdf_available"] += 1
        candidates = [_save_candidate(db, article.id, location) for location in locations]
        candidate = next(
            (item for item in candidates if item.license),
            candidates[0],
        )
        if require_known_license and not candidate.license:
            counts["missing_known_license"] += 1
            candidate.status = "LICENSE_REVIEW_REQUIRED"
            items.append(_preview_item(article, candidate.status, candidate))
            continue
        candidate.status = "ELIGIBLE"
        counts["eligible_for_download"] += 1
        items.append(_preview_item(article, candidate.status, candidate))
    db.commit()
    return {
        "project_id": project.id,
        "project_slug": project.slug,
        "download_enabled": settings.allow_pdf_downloads,
        "require_known_license": require_known_license,
        "counts": counts,
        "items": items,
    }


def acquire_pdfs(
    db: Session,
    project_id: str,
    max_articles: int,
    require_known_license: bool,
    settings: Settings,
    connector: UnpaywallConnector | None = None,
    downloader: SafePdfDownloader | None = None,
    zenodo_connector: ZenodoConnector | None = None,
    article_ids: list[str] | None = None,
) -> dict:
    if not settings.allow_pdf_downloads:
        raise PdfAcquisitionError(
            "Downloads desabilitados. Revise o preview e defina ALLOW_PDF_DOWNLOADS=true."
        )
    preview = preview_acquisition(
        db,
        project_id,
        max_articles,
        require_known_license,
        settings,
        connector,
        zenodo_connector,
        article_ids,
    )
    project = db.get(Project, project_id)
    assert project is not None
    pdf_downloader = downloader or SafePdfDownloader(settings)
    completed = 0
    failed = 0
    results: list[dict] = []
    for item in preview["items"]:
        if item["status"] != "ELIGIBLE":
            continue
        candidate = db.get(FullTextCandidate, item["candidate_id"])
        article = db.get(Article, item["article_id"])
        if candidate is None or article is None:
            continue
        attempt = DownloadAttempt(candidate_id=candidate.id, status="RUNNING")
        db.add(attempt)
        db.commit()
        destination = _destination(settings, project.slug, article)
        try:
            downloaded = pdf_downloader.download(candidate.source_url, destination)
            asset = FullTextAsset(
                article_id=article.id,
                candidate_id=candidate.id,
                storage_path=str(downloaded.path),
                sha256=downloaded.sha256,
                mime_type=downloaded.content_type,
                file_size_bytes=downloaded.file_size_bytes,
                page_count=downloaded.page_count,
                license=candidate.license,
                source_url=downloaded.final_url,
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
                    page_count=downloaded.page_count,
                    warnings=[],
                )
            )
            candidate.status = "DOWNLOADED"
            attempt.status = "COMPLETED"
            attempt.http_status = 200
            attempt.bytes_downloaded = downloaded.file_size_bytes
            attempt.sha256 = downloaded.sha256
            attempt.finished_at = datetime.now(timezone.utc)
            completed += 1
            results.append(
                {
                    "article_id": article.id,
                    "article_code": article.code,
                    "status": "COMPLETED",
                    "asset_id": asset.id,
                    "path": str(downloaded.path),
                    "sha256": downloaded.sha256,
                    "page_count": downloaded.page_count,
                }
            )
            db.commit()
        except Exception as exc:
            attempt.status = "FAILED"
            attempt.error = str(exc)[:4000]
            attempt.finished_at = datetime.now(timezone.utc)
            candidate.status = "DOWNLOAD_FAILED"
            failed += 1
            results.append(
                {
                    "article_id": article.id,
                    "article_code": article.code,
                    "status": "FAILED",
                    "error": str(exc),
                }
            )
            db.commit()
    _write_manifest(db, project, settings)
    db.add(
        WorkflowEvent(
            project_id=project.id,
            event_type="PDF_ACQUISITION_COMPLETED",
            actor="pdf-acquisition-service",
            payload={"completed": completed, "failed": failed},
        )
    )
    db.commit()
    return {
        "project_id": project.id,
        "project_slug": project.slug,
        "completed": completed,
        "failed": failed,
        "results": results,
    }


def list_assets(db: Session, project_id: str) -> list[dict]:
    statement = (
        select(FullTextAsset, Article)
        .join(Article, Article.id == FullTextAsset.article_id)
        .where(Article.project_id == project_id)
        .order_by(Article.code)
    )
    return [
        {
            "asset_id": asset.id,
            "article_id": article.id,
            "article_code": article.code,
            "title": article.title,
            "doi": article.doi,
            "storage_path": asset.storage_path,
            "sha256": asset.sha256,
            "page_count": asset.page_count,
            "license": asset.license,
            "source_url": asset.source_url,
            "validation_status": asset.validation_status,
        }
        for asset, article in db.execute(statement)
    ]


def _save_candidate(
    db: Session, article_id: str, location: OpenAccessLocation
) -> FullTextCandidate:
    candidate = db.scalar(
        select(FullTextCandidate).where(
            FullTextCandidate.article_id == article_id,
            FullTextCandidate.source_url == location.pdf_url,
        )
    )
    if candidate is None:
        candidate = FullTextCandidate(
            article_id=article_id,
            provider=location.provider,
            source_url=location.pdf_url,
            landing_page_url=location.landing_page_url,
            license=location.license,
            version=location.version,
            host_type=location.host_type,
            raw_payload=location.raw_payload,
        )
        db.add(candidate)
        db.flush()
    return candidate


def _embedded_locations(article: Article) -> list[OpenAccessLocation]:
    locations: list[OpenAccessLocation] = []
    for item in article.oa_locations or []:
        if not item.get("pdf_url"):
            continue
        locations.append(
            OpenAccessLocation(
                pdf_url=item["pdf_url"],
                landing_page_url=item.get("landing_page_url"),
                license=item.get("license"),
                version=item.get("version"),
                host_type=item.get("host_type") or "repository",
                raw_payload=item,
                provider=item.get("provider") or "discovery_provider",
            )
        )
    return locations


def _stored_candidate_locations(db: Session, article_id: str) -> list[OpenAccessLocation]:
    candidates = list(
        db.scalars(
            select(FullTextCandidate)
            .where(FullTextCandidate.article_id == article_id)
            .order_by(FullTextCandidate.discovered_at.desc())
        )
    )
    return [
        OpenAccessLocation(
            pdf_url=item.source_url,
            landing_page_url=item.landing_page_url,
            license=item.license,
            version=item.version,
            host_type=item.host_type,
            raw_payload=item.raw_payload or {},
            provider=item.provider,
        )
        for item in candidates
    ]


def _preview_item(
    article: Article,
    status: str,
    candidate: FullTextCandidate | None,
    asset_id: str | None = None,
    error: str | None = None,
) -> dict:
    return {
        "article_id": article.id,
        "article_code": article.code,
        "title": article.title,
        "doi": article.doi,
        "status": status,
        "candidate_id": candidate.id if candidate else None,
        "license": candidate.license if candidate else None,
        "version": candidate.version if candidate else None,
        "host_type": candidate.host_type if candidate else None,
        "asset_id": asset_id,
        "error": error,
    }


def _destination(settings: Settings, project_slug: str, article: Article) -> Path:
    safe_doi = re.sub(r"[^a-zA-Z0-9._-]+", "_", article.doi or "sem-doi").strip("_")
    filename = f"{article.code}__{safe_doi}.pdf"
    return Path(settings.pdf_storage_root) / project_slug / "pdfs" / filename


def _write_manifest(db: Session, project: Project, settings: Settings) -> None:
    assets = list_assets(db, project.id)
    manifest_path = Path(settings.pdf_storage_root) / project.slug / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "project_id": project.id,
        "project_slug": project.slug,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assets": assets,
    }
    temporary = manifest_path.with_suffix(".json.part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(manifest_path)
