import hashlib
import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from pypdf import PdfReader

from ..config import Settings


class PdfDownloadError(RuntimeError):
    pass


@dataclass(slots=True)
class PdfDownloadResult:
    path: Path
    sha256: str
    file_size_bytes: int
    page_count: int
    encrypted: bool
    content_type: str
    final_url: str


def validate_public_https_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise PdfDownloadError("Somente URLs HTTPS são permitidas.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise PdfDownloadError("URL de PDF inválida.")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise PdfDownloadError("Não foi possível resolver o domínio do PDF.") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise PdfDownloadError("O domínio do PDF resolve para um endereço não público.")


class SafePdfDownloader:
    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        url_validator: Callable[[str], None] = validate_public_https_url,
    ):
        self.max_bytes = settings.max_pdf_size_mb * 1024 * 1024
        self.url_validator = url_validator
        self.client = client or httpx.Client(
            timeout=settings.pdf_download_timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": settings.academic_api_user_agent},
        )

    def download(self, url: str, destination: Path) -> PdfDownloadResult:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        parsed_url = urlparse(url)
        current_url = (
            urlunparse(parsed_url._replace(scheme="https"))
            if parsed_url.scheme == "http"
            else url
        )
        try:
            for _ in range(6):
                self.url_validator(current_url)
                with self.client.stream("GET", current_url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise PdfDownloadError("Redirecionamento sem destino.")
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    declared_size = int(response.headers.get("content-length", "0") or 0)
                    if declared_size > self.max_bytes:
                        raise PdfDownloadError("O PDF excede o limite configurado.")
                    content_type = (
                        response.headers.get("content-type", "")
                        .split(";")[0]
                        .split(",")[0]
                        .strip()
                        .lower()
                    )
                    digest = hashlib.sha256()
                    total = 0
                    prefix = b""
                    with temporary.open("wb") as stream:
                        for chunk in response.iter_bytes():
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > self.max_bytes:
                                raise PdfDownloadError("O PDF excede o limite configurado.")
                            if len(prefix) < 5:
                                prefix = (prefix + chunk)[:5]
                            digest.update(chunk)
                            stream.write(chunk)
                    if prefix != b"%PDF-":
                        raise PdfDownloadError("O arquivo recebido não possui assinatura PDF.")
                    try:
                        reader = PdfReader(temporary)
                        encrypted = reader.is_encrypted
                        if encrypted:
                            raise PdfDownloadError("PDF criptografado não pode entrar no corpus.")
                        page_count = len(reader.pages)
                    except PdfDownloadError:
                        raise
                    except Exception as exc:
                        raise PdfDownloadError("O arquivo não pôde ser aberto como PDF.") from exc
                    if page_count < 1:
                        raise PdfDownloadError("O PDF não contém páginas legíveis.")
                    if content_type not in {"application/pdf", "application/octet-stream", ""}:
                        raise PdfDownloadError(
                            f"Tipo de conteúdo incompatível com PDF: {content_type}."
                        )
                    temporary.replace(destination)
                    return PdfDownloadResult(
                        path=destination,
                        sha256=digest.hexdigest(),
                        file_size_bytes=total,
                        page_count=page_count,
                        encrypted=False,
                        content_type=content_type or "application/pdf",
                        final_url=current_url,
                    )
            raise PdfDownloadError("Número máximo de redirecionamentos excedido.")
        finally:
            temporary.unlink(missing_ok=True)
