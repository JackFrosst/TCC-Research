import re

import httpx

from ..config import Settings
from .unpaywall import OpenAccessLocation


class ZenodoConnector:
    """Resolve arquivos publicos de um registro Zenodo identificado por DOI."""

    base_url = "https://zenodo.org/api/records"
    doi_pattern = re.compile(r"^10\.5281/zenodo\.(\d+)$", re.IGNORECASE)

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.client = client or httpx.Client(
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": settings.academic_api_user_agent},
        )

    def find_pdf(self, doi: str) -> OpenAccessLocation | None:
        match = self.doi_pattern.fullmatch(doi.strip())
        if not match:
            return None
        response = self.client.get(f"{self.base_url}/{match.group(1)}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        metadata = payload.get("metadata") or {}
        if metadata.get("access_right") not in {None, "open"}:
            return None
        files = payload.get("files") or []
        pdf = next(
            (
                item
                for item in files
                if str(item.get("key") or item.get("filename") or "").lower().endswith(".pdf")
            ),
            None,
        )
        if not pdf:
            return None
        links = pdf.get("links") or {}
        pdf_url = links.get("content") or links.get("download") or links.get("self")
        if not pdf_url:
            return None
        license_data = metadata.get("license")
        license_id = (
            license_data.get("id") if isinstance(license_data, dict) else license_data
        )
        record_url = (payload.get("links") or {}).get("html")
        return OpenAccessLocation(
            pdf_url=pdf_url,
            landing_page_url=record_url,
            license=license_id,
            version="submittedVersion",
            host_type="repository",
            raw_payload={
                "record_id": payload.get("id"),
                "doi": metadata.get("doi"),
                "filename": pdf.get("key") or pdf.get("filename"),
                "checksum": pdf.get("checksum"),
            },
            provider="zenodo",
        )
