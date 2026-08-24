from __future__ import annotations

import hashlib
import ipaddress
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from forgegraph.catalog.models import EvidenceSource
from forgegraph.core.settings import Settings


@dataclass(frozen=True)
class RetrievedDocument:
    source: EvidenceSource
    content_type: str
    content: bytes


class EvidencePolicyError(ValueError):
    pass


class ManufacturerEvidenceRetriever:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def validate_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise EvidencePolicyError("Evidence URL must use HTTP(S) and include a hostname.")
        hostname = parsed.hostname.lower().rstrip(".")
        allowlist = self.settings.manufacturer_domain_set
        if not allowlist:
            raise EvidencePolicyError("Manufacturer domain allowlist is empty.")
        if not any(hostname == domain or hostname.endswith(f".{domain}") for domain in allowlist):
            raise EvidencePolicyError("Evidence URL is outside the manufacturer domain allowlist.")
        self._reject_private_host(hostname)
        return parsed._replace(netloc=hostname).geturl()

    def fetch(self, url: str) -> RetrievedDocument:
        validated_url = self.validate_url(url)
        timeout = httpx.Timeout(self.settings.request_timeout_seconds)
        limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
        headers = {"User-Agent": self.settings.retrieval_user_agent}
        with httpx.Client(
            timeout=timeout,
            limits=limits,
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = client.get(validated_url)
            final_url = self.validate_url(str(response.url))
            response.raise_for_status()
            content_length = int(response.headers.get("content-length", "0") or 0)
            if content_length > self.settings.max_fetch_bytes:
                raise EvidencePolicyError("Evidence document exceeds the configured size limit.")
            content = response.content
            if len(content) > self.settings.max_fetch_bytes:
                raise EvidencePolicyError("Evidence document exceeds the configured size limit.")
            content_type = response.headers.get("content-type", "application/octet-stream").split(
                ";", 1
            )[0]
        text, page = self._extract_text(content, content_type)
        title = self._title(text, final_url)
        source = EvidenceSource(
            url=final_url,
            source_type="manufacturer",
            title=title,
            document_hash=hashlib.sha256(content).hexdigest(),
            retrieved_at=datetime.now(UTC),
            page=page,
            evidence_text=text[:50_000] if text else None,
        )
        return RetrievedDocument(source, content_type, content)

    @staticmethod
    def _reject_private_host(hostname: str) -> None:
        try:
            addresses = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise EvidencePolicyError("Evidence hostname could not be resolved.") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise EvidencePolicyError("Evidence URL resolves to a non-public address.")

    @staticmethod
    def _extract_text(content: bytes, content_type: str) -> tuple[str, int | None]:
        if content_type == "application/pdf" or content[:4] == b"%PDF":
            try:
                import fitz  # type: ignore[import-not-found]

                document = fitz.open(stream=content, filetype="pdf")
                pages = [page.get_text("text") for page in document]
                return "\n".join(pages), 1 if pages else None
            except Exception:
                return "", None
        if content_type in {"text/html", "application/xhtml+xml"}:
            soup = BeautifulSoup(content, "html.parser")
            for node in soup(["script", "style", "noscript"]):
                node.decompose()
            return " ".join(soup.stripped_strings), None
        try:
            return content.decode("utf-8", errors="replace"), None
        except UnicodeDecodeError:
            return "", None

    @staticmethod
    def _title(text: str, url: str) -> str:
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        return first_line[:300] or urlparse(url).hostname or "Manufacturer document"
