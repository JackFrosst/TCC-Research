from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class SearchPage:
    provider: str
    records: list[dict[str, Any]]
    next_cursor: str | None = None
    total: int | None = None


class AcademicConnector(Protocol):
    def search(
        self,
        query: str,
        year_from: int,
        year_to: int,
        limit: int,
        cursor: str | None = None,
    ) -> SearchPage: ...
