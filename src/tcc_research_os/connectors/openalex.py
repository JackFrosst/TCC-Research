import httpx

from ..config import Settings
from .base import SearchPage
from .http import request_with_retry


class OpenAlexConnector:
    base_url = "https://api.openalex.org/works"
    fields = (
        "id,doi,title,display_name,publication_year,language,authorships,"
        "primary_location,best_oa_location,open_access,ids,type,referenced_works"
    )

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
            "search": query,
            "filter": (
                f"from_publication_date:{year_from}-01-01,to_publication_date:{year_to}-12-31"
            ),
            "per_page": min(limit, 100),
            "cursor": cursor or "*",
            "select": self.fields,
        }
        if self.settings.openalex_api_key:
            params["api_key"] = self.settings.openalex_api_key
        response = request_with_retry(
            self.client, "GET", self.base_url, self.settings, params=params
        )
        response.raise_for_status()
        payload = response.json()
        meta = payload.get("meta", {})
        return SearchPage(
            provider="openalex",
            records=payload.get("results", []),
            next_cursor=meta.get("next_cursor"),
            total=meta.get("count"),
        )

    def related(
        self, identifier: str, direction: str, limit: int, cursor: str | None = None
    ) -> SearchPage:
        seed = self._resolve_work(identifier)
        if seed is None:
            return SearchPage("openalex", [])
        if direction == "forward":
            params = {
                "filter": f"cites:{seed['id'].rsplit('/', 1)[-1]}",
                "per_page": min(limit, 100),
                "cursor": cursor or "*",
                "select": self.fields,
            }
            if self.settings.openalex_api_key:
                params["api_key"] = self.settings.openalex_api_key
            response = request_with_retry(
                self.client, "GET", self.base_url, self.settings, params=params
            )
            response.raise_for_status()
            payload = response.json()
            return SearchPage(
                "openalex",
                payload.get("results", []),
                payload.get("meta", {}).get("next_cursor"),
                payload.get("meta", {}).get("count"),
            )
        references = (seed.get("referenced_works") or [])[:limit]
        records = [work for work_id in references if (work := self._resolve_work(work_id))]
        return SearchPage("openalex", records, total=len(references))

    def _resolve_work(self, identifier: str) -> dict | None:
        if identifier.startswith("DOI:"):
            params = {"filter": f"doi:{identifier[4:]}", "per_page": 1, "select": self.fields}
            if self.settings.openalex_api_key:
                params["api_key"] = self.settings.openalex_api_key
            response = request_with_retry(
                self.client, "GET", self.base_url, self.settings, params=params
            )
            response.raise_for_status()
            results = response.json().get("results", [])
            return results[0] if results else None
        work_id = identifier.rsplit("/", 1)[-1]
        params = {"select": self.fields}
        if self.settings.openalex_api_key:
            params["api_key"] = self.settings.openalex_api_key
        response = request_with_retry(
            self.client, "GET", f"{self.base_url}/{work_id}", self.settings, params=params
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
