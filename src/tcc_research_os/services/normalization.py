import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "http://dx.doi.org/",
    "https://dx.doi.org/",
    "doi:",
)


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    for prefix in DOI_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    normalized = normalized.strip().rstrip(".,;)")
    return normalized if normalized.startswith("10.") and "/" in normalized else None


def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
    return " ".join(text.split())


def strip_markup(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"<[^>]+>", " ", value).replace("  ", " ").strip()


@dataclass(slots=True)
class NormalizedRecord:
    provider: str
    provider_id: str
    title: str
    normalized_title: str
    raw_payload: dict[str, Any]
    doi: str | None = None
    abstract: str | None = None
    year: int | None = None
    journal: str | None = None
    language: str | None = None
    authors: list[dict[str, Any]] = field(default_factory=list)
    external_ids: dict[str, str] = field(default_factory=dict)
    document_type: str | None = None
    peer_reviewed: bool | None = None
    oa_locations: list[dict[str, Any]] = field(default_factory=list)


def normalize_crossref(item: dict[str, Any]) -> NormalizedRecord | None:
    titles = item.get("title") or []
    title = titles[0].strip() if titles else ""
    if not title:
        return None
    date_parts = (item.get("published") or item.get("issued") or {}).get("date-parts", [])
    year = date_parts[0][0] if date_parts and date_parts[0] else None
    containers = item.get("container-title") or []
    authors = [
        {
            "given": author.get("given"),
            "family": author.get("family"),
            "orcid": author.get("ORCID"),
        }
        for author in item.get("author", [])
    ]
    provider_id = item.get("DOI") or item.get("URL") or title
    return NormalizedRecord(
        provider="crossref",
        provider_id=str(provider_id),
        title=title,
        normalized_title=normalize_title(title),
        doi=normalize_doi(item.get("DOI")),
        abstract=strip_markup(item.get("abstract")),
        year=year,
        journal=containers[0] if containers else None,
        language=item.get("language"),
        authors=authors,
        external_ids={"doi": normalize_doi(item.get("DOI"))} if item.get("DOI") else {},
        document_type=item.get("type"),
        peer_reviewed=item.get("type") == "journal-article",
        raw_payload=item,
    )


def normalize_scielo_crossref(item: dict[str, Any]) -> NormalizedRecord | None:
    record = normalize_crossref(item)
    if record is None:
        return None
    record.provider = "scielo_crossref"
    return record


def normalize_openalex(item: dict[str, Any]) -> NormalizedRecord | None:
    title = (item.get("title") or item.get("display_name") or "").strip()
    if not title:
        return None
    authors = [
        {
            "name": entry.get("author", {}).get("display_name"),
            "orcid": entry.get("author", {}).get("orcid"),
        }
        for entry in item.get("authorships", [])
    ]
    source = ((item.get("primary_location") or {}).get("source") or {}).get("display_name")
    ids = item.get("ids") or {}
    best_oa = item.get("best_oa_location") or {}
    oa_locations = []
    if best_oa.get("pdf_url"):
        oa_locations.append(
            {
                "provider": "openalex",
                "pdf_url": best_oa["pdf_url"],
                "landing_page_url": best_oa.get("landing_page_url"),
                "license": best_oa.get("license"),
                "version": best_oa.get("version"),
            }
        )
    return NormalizedRecord(
        provider="openalex",
        provider_id=str(item.get("id") or title),
        title=title,
        normalized_title=normalize_title(title),
        doi=normalize_doi(item.get("doi") or ids.get("doi")),
        abstract=None,
        year=item.get("publication_year"),
        journal=source,
        language=item.get("language"),
        authors=authors,
        external_ids={key: str(value) for key, value in ids.items() if value},
        document_type=item.get("type"),
        peer_reviewed=None,
        oa_locations=oa_locations,
        raw_payload=item,
    )


def normalize_semantic_scholar(item: dict[str, Any]) -> NormalizedRecord | None:
    title = (item.get("title") or "").strip()
    if not title:
        return None
    external = {str(k).lower(): str(v) for k, v in (item.get("externalIds") or {}).items() if v}
    pdf = item.get("openAccessPdf") or {}
    publication_types = item.get("publicationTypes") or []
    return NormalizedRecord(
        provider="semantic_scholar",
        provider_id=str(item.get("paperId") or title),
        title=title,
        normalized_title=normalize_title(title),
        doi=normalize_doi(external.get("doi")),
        abstract=item.get("abstract"),
        year=item.get("year"),
        journal=item.get("venue"),
        authors=[
            {"name": author.get("name"), "id": author.get("authorId")}
            for author in item.get("authors", [])
        ],
        external_ids=external,
        document_type=publication_types[0] if publication_types else None,
        peer_reviewed=None,
        oa_locations=[
            {
                "provider": "semantic_scholar",
                "pdf_url": pdf.get("url"),
                "license": pdf.get("license"),
            }
        ]
        if pdf.get("url")
        else [],
        raw_payload=item,
    )


def normalize_dblp(item: dict[str, Any]) -> NormalizedRecord | None:
    title = strip_markup(str(item.get("title") or "")) or ""
    if not title:
        return None
    authors_value = (item.get("authors") or {}).get("author", [])
    if isinstance(authors_value, dict):
        authors_value = [authors_value]
    return NormalizedRecord(
        provider="dblp",
        provider_id=str(item.get("key") or item.get("url") or title),
        title=title,
        normalized_title=normalize_title(title),
        doi=normalize_doi(item.get("doi")),
        year=int(item["year"]) if str(item.get("year", "")).isdigit() else None,
        journal=item.get("venue"),
        authors=[
            {"name": author.get("text") if isinstance(author, dict) else str(author)}
            for author in authors_value
        ],
        external_ids={"dblp": str(item.get("key"))} if item.get("key") else {},
        document_type=item.get("type"),
        peer_reviewed=True
        if item.get("type") in {"Journal Articles", "Conference and Workshop Papers"}
        else None,
        raw_payload=item,
    )


def normalize_arxiv(item: dict[str, Any]) -> NormalizedRecord | None:
    title = " ".join((item.get("title") or "").split())
    if not title:
        return None
    identifier = str(item.get("id") or title).rsplit("/", 1)[-1]
    published = item.get("published") or ""
    return NormalizedRecord(
        provider="arxiv",
        provider_id=str(item.get("id") or title),
        title=title,
        normalized_title=normalize_title(title),
        doi=normalize_doi(item.get("doi")),
        abstract=" ".join((item.get("summary") or "").split()) or None,
        year=int(published[:4]) if published[:4].isdigit() else None,
        journal=item.get("journal_ref"),
        authors=[{"name": name} for name in item.get("authors", [])],
        external_ids={"arxiv": identifier},
        document_type="preprint",
        peer_reviewed=False,
        oa_locations=[
            {
                "provider": "arxiv",
                "pdf_url": item.get("pdf_url"),
                "landing_page_url": item.get("landing_page_url"),
                "license": item.get("license"),
            }
        ]
        if item.get("pdf_url")
        else [],
        raw_payload=item,
    )


def normalize_datacite(item: dict[str, Any]) -> NormalizedRecord | None:
    attributes = item.get("attributes") or {}
    titles = attributes.get("titles") or []
    title = (titles[0].get("title") if titles else "") or ""
    if not title:
        return None
    creators = attributes.get("creators") or []
    return NormalizedRecord(
        provider="datacite",
        provider_id=str(item.get("id") or title),
        title=title,
        normalized_title=normalize_title(title),
        doi=normalize_doi(attributes.get("doi") or item.get("id")),
        abstract=next(
            (
                desc.get("description")
                for desc in attributes.get("descriptions", [])
                if desc.get("descriptionType") == "Abstract"
            ),
            None,
        ),
        year=attributes.get("publicationYear"),
        journal=attributes.get("publisher"),
        language=attributes.get("language"),
        authors=[
            {
                "name": creator.get("name"),
                "orcid": next(
                    (
                        name.get("nameIdentifier")
                        for name in creator.get("nameIdentifiers", [])
                        if name.get("nameIdentifierScheme") == "ORCID"
                    ),
                    None,
                ),
            }
            for creator in creators
        ],
        external_ids={"doi": str(attributes.get("doi") or item.get("id"))},
        document_type=(attributes.get("types") or {}).get("resourceTypeGeneral"),
        peer_reviewed=None,
        raw_payload=item,
    )


def normalize_europe_pmc(item: dict[str, Any]) -> NormalizedRecord | None:
    title = (item.get("title") or "").strip()
    if not title:
        return None
    external = {key: str(item[key]) for key in ("doi", "pmid", "pmcid") if item.get(key)}
    urls = item.get("fullTextUrlList", {}).get("fullTextUrl", [])
    oa_locations = [
        {
            "provider": "europe_pmc",
            "pdf_url": url.get("url"),
            "license": url.get("availabilityCode"),
        }
        for url in urls
        if url.get("documentStyle") == "pdf" and url.get("url")
    ]
    return NormalizedRecord(
        provider="europe_pmc",
        provider_id=str(item.get("id") or item.get("pmid") or title),
        title=title,
        normalized_title=normalize_title(title),
        doi=normalize_doi(item.get("doi")),
        abstract=item.get("abstractText"),
        year=int(item["pubYear"]) if str(item.get("pubYear", "")).isdigit() else None,
        journal=item.get("journalTitle"),
        authors=[
            {
                "name": author.get("fullName"),
                "orcid": author.get("authorId") if author.get("authorIdType") == "ORCID" else None,
            }
            for author in item.get("authorList", {}).get("author", [])
        ],
        external_ids=external,
        document_type=item.get("pubType"),
        peer_reviewed=True if item.get("pubType") == "journal article" else None,
        oa_locations=oa_locations,
        raw_payload=item,
    )


def normalize_scielo(item: dict[str, Any]) -> NormalizedRecord | None:
    title = (item.get("title") or "").strip()
    if not title:
        return None
    return NormalizedRecord(
        provider="scielo",
        provider_id=str(item.get("id") or title),
        title=title,
        normalized_title=normalize_title(title),
        doi=normalize_doi(item.get("doi")),
        abstract=item.get("abstract"),
        year=item.get("year"),
        journal=item.get("journal"),
        language=item.get("language"),
        authors=item.get("authors") or [],
        external_ids=item.get("external_ids") or {},
        document_type=item.get("document_type"),
        peer_reviewed=item.get("peer_reviewed"),
        oa_locations=item.get("oa_locations") or [],
        raw_payload=item.get("raw_payload") or item,
    )


def normalize_openaire(item: dict[str, Any]) -> NormalizedRecord | None:
    title_value = item.get("mainTitle") or item.get("title") or ""
    title = title_value.get("value", "") if isinstance(title_value, dict) else str(title_value)
    title = title.strip()
    if not title:
        return None
    pids = item.get("pids") or item.get("pid") or []
    if isinstance(pids, dict):
        pids = [pids]
    external = {
        str(pid.get("scheme", "id")).lower(): str(pid.get("value"))
        for pid in pids
        if isinstance(pid, dict) and pid.get("value")
    }
    return NormalizedRecord(
        provider="openaire",
        provider_id=str(item.get("id") or title),
        title=title,
        normalized_title=normalize_title(title),
        doi=normalize_doi(external.get("doi")),
        abstract=item.get("description") if isinstance(item.get("description"), str) else None,
        year=item.get("publicationYear"),
        external_ids=external,
        document_type=item.get("type") or item.get("instanceType"),
        peer_reviewed=item.get("isPeerReviewed"),
        raw_payload=item,
    )


def normalize_manual(item: dict[str, Any]) -> NormalizedRecord | None:
    title = (item.get("title") or "").strip()
    if not title:
        return None
    provider = str(item.get("provider") or "manual")
    return NormalizedRecord(
        provider=provider,
        provider_id=str(item.get("provider_id") or item.get("doi") or title),
        title=title,
        normalized_title=normalize_title(title),
        doi=normalize_doi(item.get("doi")),
        abstract=item.get("abstract"),
        year=item.get("year"),
        journal=item.get("journal"),
        language=item.get("language"),
        authors=item.get("authors") or [],
        external_ids=item.get("external_ids") or {},
        document_type=item.get("document_type"),
        peer_reviewed=item.get("peer_reviewed"),
        oa_locations=item.get("oa_locations") or [],
        raw_payload=item,
    )
