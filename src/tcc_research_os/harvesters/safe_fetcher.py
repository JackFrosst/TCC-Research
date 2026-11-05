import ipaddress
import socket
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx


class RepositoryAccessError(RuntimeError):
    pass


class SafeRepositoryFetcher:
    """Fetcher para adaptadores autorizados, com defesa contra SSRF e robots.txt."""

    def __init__(
        self,
        allowed_domains: set[str],
        user_agent: str,
        client: httpx.Client | None = None,
        max_response_bytes: int = 10 * 1024 * 1024,
    ):
        self.allowed_domains = {domain.lower().strip(".") for domain in allowed_domains}
        self.user_agent = user_agent
        self.client = client or httpx.Client(timeout=30, headers={"User-Agent": user_agent})
        self.max_response_bytes = max_response_bytes
        self._robots: dict[str, RobotFileParser] = {}

    def _validate_url(self, url: str) -> tuple[str, str]:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().strip(".")
        if parsed.scheme != "https" or not host:
            raise RepositoryAccessError("Somente URLs HTTPS explícitas são permitidas.")
        if not any(
            host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains
        ):
            raise RepositoryAccessError("O domínio não pertence à lista autorizada.")
        for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
            address = ipaddress.ip_address(result[4][0])
            if not address.is_global:
                raise RepositoryAccessError("Endereços privados ou locais não são permitidos.")
        return host, parsed.path or "/"

    def _robots_parser(self, host: str) -> RobotFileParser:
        if host in self._robots:
            return self._robots[host]
        robots_url = f"https://{host}/robots.txt"
        response = self.client.get(robots_url)
        parser = RobotFileParser(robots_url)
        if response.status_code == 200:
            parser.parse(response.text.splitlines())
        elif response.status_code in {401, 403}:
            parser.parse(["User-agent: *", "Disallow: /"])
        else:
            parser.parse(["User-agent: *", "Allow: /"])
        self._robots[host] = parser
        return parser

    def get_text(self, url: str) -> str:
        host, _ = self._validate_url(url)
        if not self._robots_parser(host).can_fetch(self.user_agent, url):
            raise RepositoryAccessError("robots.txt não autoriza esta coleta.")
        with self.client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            final_host, _ = self._validate_url(str(response.url))
            if final_host != host and not any(
                final_host == domain or final_host.endswith(f".{domain}")
                for domain in self.allowed_domains
            ):
                raise RepositoryAccessError("Redirecionamento para domínio não autorizado.")
            chunks = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self.max_response_bytes:
                    raise RepositoryAccessError("Resposta excede o limite configurado.")
                chunks.append(chunk)
            return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
