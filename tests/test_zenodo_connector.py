import httpx

from tcc_research_os.config import Settings
from tcc_research_os.connectors.zenodo import ZenodoConnector


def test_zenodo_connector_returns_open_pdf():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": 123,
                "metadata": {
                    "doi": "10.5281/zenodo.123",
                    "access_right": "open",
                    "license": {"id": "cc-by-4.0"},
                },
                "links": {"html": "https://zenodo.org/records/123"},
                "files": [
                    {
                        "key": "paper.pdf",
                        "checksum": "md5:abc",
                        "links": {
                            "self": "https://zenodo.org/api/records/123/files/paper.pdf/content"
                        },
                    }
                ],
            },
            request=request,
        )

    connector = ZenodoConnector(
        Settings(), client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    location = connector.find_pdf("10.5281/zenodo.123")

    assert location is not None
    assert location.provider == "zenodo"
    assert location.license == "cc-by-4.0"
    assert location.pdf_url.endswith("paper.pdf/content")


def test_zenodo_connector_ignores_other_doi_registrants():
    connector = ZenodoConnector(Settings())

    assert connector.find_pdf("10.1000/example") is None
