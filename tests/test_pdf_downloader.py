from io import BytesIO

import httpx
import pytest
from pypdf import PdfWriter

from tcc_research_os.config import Settings
from tcc_research_os.services.pdf_downloader import (
    PdfDownloadError,
    SafePdfDownloader,
    validate_public_https_url,
)


def _pdf_bytes() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    writer.write(output)
    return output.getvalue()


def test_downloader_validates_and_saves_pdf(tmp_path):
    pdf = _pdf_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=pdf,
            headers={"content-type": "application/pdf", "content-length": str(len(pdf))},
            request=request,
        )

    downloader = SafePdfDownloader(
        Settings(max_pdf_size_mb=1),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        url_validator=lambda _: None,
    )
    result = downloader.download("https://repository.example.org/paper.pdf", tmp_path / "a.pdf")

    assert result.path.exists()
    assert result.page_count == 1
    assert len(result.sha256) == 64


def test_downloader_rejects_non_pdf(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not pdf</html>", request=request)

    downloader = SafePdfDownloader(
        Settings(max_pdf_size_mb=1),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        url_validator=lambda _: None,
    )
    with pytest.raises(PdfDownloadError, match="assinatura PDF"):
        downloader.download("https://repository.example.org/not-pdf", tmp_path / "a.pdf")


def test_url_validator_rejects_http_before_dns_lookup():
    with pytest.raises(PdfDownloadError, match="HTTPS"):
        validate_public_https_url("http://example.org/paper.pdf")


def test_downloader_upgrades_http_source_to_https(tmp_path):
    pdf = _pdf_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=pdf, request=request)

    downloader = SafePdfDownloader(
        Settings(max_pdf_size_mb=1),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        url_validator=lambda _: None,
    )
    result = downloader.download("http://example.org/article.pdf", tmp_path / "article.pdf")

    assert result.final_url == "https://example.org/article.pdf"


def test_downloader_accepts_duplicated_octet_stream_header(tmp_path):
    pdf = _pdf_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=pdf,
            headers={"content-type": "application/octet-stream, application/octet-stream"},
            request=request,
        )

    downloader = SafePdfDownloader(
        Settings(max_pdf_size_mb=1),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        url_validator=lambda _: None,
    )
    result = downloader.download("https://example.org/article.pdf", tmp_path / "article.pdf")

    assert result.content_type == "application/octet-stream"
