from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from html import unescape

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..connectors.http import request_with_retry
from ..models import (
    HarvestedRecord,
    HarvestRun,
    HarvestRunStatus,
    RepositorySource,
)
from .normalization import normalize_doi, normalize_title


class HarvestError(RuntimeError):
    pass


def get_or_create_scielo_source(db: Session, settings: Settings) -> RepositorySource:
    source = db.scalar(select(RepositorySource).where(RepositorySource.slug == "scielo"))
    if source:
        return source
    source = RepositorySource(
        slug="scielo",
        name="SciELO",
        domain="articlemeta.scielo.org",
        acquisition_method="articlemeta",
        base_url=settings.scielo_articlemeta_url,
        config={"default_collection": settings.scielo_default_collection},
    )
    db.add(source)
    db.flush()
    return source


def _value(items: list[dict] | None, language: str | None = None) -> str | None:
    if not items:
        return None
    preferred = next((item for item in items if language and item.get("l") == language), items[0])
    return unescape(str(preferred.get("_") or preferred.get("a") or "")).strip() or None


def _canonicalize(payload: dict) -> dict:
    article = payload.get("article") or {}
    language = _value(article.get("v40"))
    title = _value(article.get("v12"), language) or ""
    abstract = _value(article.get("v83"), language)
    authors = [
        {
            "given": entry.get("n"),
            "family": entry.get("s"),
            "orcid": entry.get("k"),
        }
        for entry in article.get("v10", [])
    ]
    fulltexts = payload.get("fulltexts") or {}
    locations = []
    for kind, languages in fulltexts.items():
        for lang, url in (languages or {}).items():
            locations.append(
                {
                    "provider": "scielo",
                    "landing_page_url": str(url).replace("http://", "https://"),
                    "format": kind,
                    "language": lang,
                    "license": "open-access",
                }
            )
    year_value = payload.get("publication_year") or payload.get("publication_date")
    return {
        "external_id": str(payload.get("code") or article.get("code")),
        "title": title,
        "abstract": abstract,
        "year": int(str(year_value)[:4]) if str(year_value)[:4].isdigit() else None,
        "journal": _value(article.get("v100")),
        "doi": normalize_doi(payload.get("doi") or _value(article.get("v237"))),
        "language": language,
        "authors": authors,
        "external_ids": {"scielo": str(payload.get("code"))},
        "document_type": payload.get("document_type"),
        "peer_reviewed": payload.get("document_type") == "research-article",
        "oa_locations": locations,
        "canonical_url": locations[0]["landing_page_url"] if locations else None,
    }


def harvest_scielo(
    db: Session,
    settings: Settings,
    collection: str,
    from_date: str,
    until_date: str,
    max_records: int,
    idempotency_key: str,
    client: httpx.Client | None = None,
) -> HarvestRun:
    previous = db.scalar(select(HarvestRun).where(HarvestRun.idempotency_key == idempotency_key))
    if previous:
        return previous
    if from_date > until_date:
        raise HarvestError("from_date deve ser anterior ou igual a until_date.")
    source = get_or_create_scielo_source(db, settings)
    run = HarvestRun(
        source_id=source.id,
        idempotency_key=idempotency_key,
        status=HarvestRunStatus.running,
        checkpoint={"collection": collection, "offset": 0},
    )
    db.add(run)
    db.flush()
    http = client or httpx.Client(
        timeout=settings.request_timeout_seconds,
        headers={"User-Agent": settings.repository_crawl_user_agent},
    )
    maximum = min(max_records, settings.repository_harvest_max_records)
    try:
        response = request_with_retry(
            http,
            "GET",
            f"{settings.scielo_articlemeta_url.rstrip('/')}/api/v1/article/identifiers/",
            settings,
            params={
                "collection": collection,
                "from": from_date,
                "until": until_date,
                "limit": maximum,
                "offset": 0,
            },
        )
        response.raise_for_status()
        identifiers = response.json().get("objects", [])[:maximum]
        for index, identifier in enumerate(identifiers, start=1):
            detail = request_with_retry(
                http,
                "GET",
                f"{settings.scielo_articlemeta_url.rstrip('/')}/api/v1/article/",
                settings,
                params={
                    "collection": identifier.get("collection", collection),
                    "code": identifier["code"],
                    "format": "json",
                },
            )
            detail.raise_for_status()
            payload = detail.json()
            normalized = _canonicalize(payload)
            if not normalized["title"]:
                continue
            serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
            digest = hashlib.sha256(serialized).hexdigest()
            record = db.scalar(
                select(HarvestedRecord).where(
                    HarvestedRecord.source_id == source.id,
                    HarvestedRecord.external_id == normalized["external_id"],
                )
            )
            if record is None:
                record = HarvestedRecord(
                    source_id=source.id,
                    external_id=normalized["external_id"],
                    title=normalized["title"],
                    normalized_title=normalize_title(normalized["title"]),
                    raw_payload=payload,
                    content_hash=digest,
                )
                db.add(record)
                run.records_created += 1
            elif record.content_hash != digest:
                run.records_updated += 1
            for field in (
                "canonical_url",
                "abstract",
                "year",
                "journal",
                "doi",
                "language",
                "authors",
                "external_ids",
                "document_type",
                "peer_reviewed",
                "oa_locations",
            ):
                setattr(record, field, normalized[field])
            record.raw_payload = payload
            record.content_hash = digest
            record.last_seen_at = datetime.now(timezone.utc)
            run.records_received += 1
            run.checkpoint = {"collection": collection, "offset": index, "code": identifier["code"]}
            db.flush()
        run.status = HarvestRunStatus.completed
        run.finished_at = datetime.now(timezone.utc)
        source.last_checked_at = run.finished_at
        db.commit()
        db.refresh(run)
        return run
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        run.status = HarvestRunStatus.failed
        run.error = str(exc)
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise HarvestError(f"Falha na coleta SciELO: {exc}") from exc
