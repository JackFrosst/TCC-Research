from dataclasses import dataclass
from urllib.parse import quote

import httpx

from ..config import Settings


class UnpaywallConfigurationError(RuntimeError):
    pass


@dataclass(slots=True)
class OpenAccessLocation:
    pdf_url: str
    landing_page_url: str | None
    license: str | None
    version: str | None
    host_type: str | None
    raw_payload: dict
    provider: str = "unpaywall"


class UnpaywallConnector:
    base_url = "https://api.unpaywall.org/v2"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        email = settings.unpaywall_email or settings.academic_api_email
        if not _is_real_email(email):
            raise UnpaywallConfigurationError(
                "Configure UNPAYWALL_EMAIL com um endereço real antes de consultar PDFs."
            )
        self.email = email
        self.client = client or httpx.Client(
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": settings.academic_api_user_agent},
        )

    def find_pdf(self, doi: str) -> OpenAccessLocation | None:
        response = self.client.get(
            f"{self.base_url}/{quote(doi, safe='/')}", params={"email": self.email}
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        if not payload.get("is_oa"):
            return None
        locations = [payload.get("best_oa_location"), *(payload.get("oa_locations") or [])]
        for location in locations:
            if not location or not location.get("url_for_pdf"):
                continue
            return OpenAccessLocation(
                pdf_url=location["url_for_pdf"],
                landing_page_url=location.get("url_for_landing_page") or location.get("url"),
                license=location.get("license"),
                version=location.get("version"),
                host_type=location.get("host_type"),
                raw_payload=payload,
            )
        return None


def _is_real_email(value: str | None) -> bool:
    if not value or "@" not in value:
        return False
    lowered = value.strip().lower()
    return not lowered.endswith(("@example.com", "@example.invalid", ".invalid"))
