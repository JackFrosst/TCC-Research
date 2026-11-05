import httpx

from ..config import Settings
from .base import SearchPage
from .http import request_with_retry


class EuropePmcConnector:
    base_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": settings.academic_api_user_agent},
        )

    def search(
        self, query: str, year_from: int, year_to: int, limit: int, cursor: str | None = None
    ) -> SearchPage:
        params = {
            "query": f"({query}) AND FIRST_PDATE:[{year_from}-01-01 TO {year_to}-12-31]",
            "resultType": "core",
            "format": "json",
            "pageSize": min(limit, 1000),
            "cursorMark": cursor or "*",
            "email": self.settings.academic_api_email,
        }
        response = request_with_retry(
            self.client, "GET", self.base_url, self.settings, params=params
        )
        response.raise_for_status()
        payload = response.json()
        return SearchPage(
            "europe_pmc",
            payload.get("resultList", {}).get("result", []),
            payload.get("nextCursorMark"),
            payload.get("hitCount"),
        )
