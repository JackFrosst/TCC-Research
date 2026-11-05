import httpx
import pytest

from tcc_research_os.config import Settings
from tcc_research_os.connectors.unpaywall import (
    UnpaywallConfigurationError,
    UnpaywallConnector,
)


def test_unpaywall_requires_real_email():
    with pytest.raises(UnpaywallConfigurationError):
        UnpaywallConnector(Settings(unpaywall_email="seu-email@example.com"))


def test_unpaywall_returns_best_pdf_location():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "is_oa": True,
                "best_oa_location": {
                    "url_for_pdf": "https://repository.example.org/paper.pdf",
                    "url_for_landing_page": "https://repository.example.org/paper",
                    "license": "cc-by",
                    "version": "publishedVersion",
                    "host_type": "repository",
                },
                "oa_locations": [],
            },
            request=request,
        )

    connector = UnpaywallConnector(
        Settings(unpaywall_email="researcher@university.edu"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    location = connector.find_pdf("10.1234/example")

    assert location is not None
    assert location.license == "cc-by"
    assert location.pdf_url.endswith("paper.pdf")
