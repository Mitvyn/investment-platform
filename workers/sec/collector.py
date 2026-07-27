from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from workers.http import trusted_ssl_context

from .models import CollectedFiling, FilingRequest

ACCESSION_PATTERN = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
CIK_PATTERN = re.compile(r"^[0-9]{1,10}$")
DOCUMENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+\.html?$")
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class SecCollectorError(RuntimeError):
    """Raised when SEC input or transport response is invalid."""


@dataclass(frozen=True, slots=True)
class SecSettings:
    user_agent: str
    base_url: str = "https://www.sec.gov"
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        if not EMAIL_PATTERN.search(self.user_agent):
            raise ValueError("SEC user agent must include a monitored email address")


@dataclass(frozen=True, slots=True)
class BytesResponse:
    body: bytes
    status: int
    headers: Mapping[str, str]
    final_url: str | None = None


class BytesTransport(Protocol):
    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> BytesResponse: ...


class UrllibBytesTransport:
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self.ssl_context = trusted_ssl_context()

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> BytesResponse:
        request = Request(url, headers=dict(headers), method="GET")
        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
                context=self.ssl_context,
            ) as response:
                return BytesResponse(
                    body=response.read(),
                    status=response.status,
                    headers=dict(response.headers.items()),
                    final_url=response.geturl(),
                )
        except HTTPError as error:
            raise SecCollectorError(
                f"SEC returned HTTP {error.code} for filing request"
            ) from error
        except URLError as error:
            raise SecCollectorError("could not reach SEC filing archive") from error


class SecCollector:
    def __init__(
        self,
        settings: SecSettings,
        *,
        transport: BytesTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibBytesTransport(settings.timeout_seconds)
        self.clock = clock or (lambda: datetime.now(UTC))

    def fetch_filing(self, filing: FilingRequest) -> CollectedFiling:
        source_url = self.filing_url(filing)
        response = self.transport.request(
            source_url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": self.settings.user_agent,
            },
        )
        if not 200 <= response.status < 300:
            raise SecCollectorError(
                f"SEC returned HTTP {response.status} for filing request"
            )

        try:
            html = response.body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SecCollectorError("SEC filing was not valid UTF-8") from error

        return CollectedFiling(
            request=filing,
            source_url=source_url,
            retrieved_at=self.clock().astimezone(UTC).isoformat(),
            html=html,
            content_sha256=hashlib.sha256(response.body).hexdigest(),
        )

    def filing_url(self, filing: FilingRequest) -> str:
        cik = filing.cik.lstrip("0") or "0"
        if not CIK_PATTERN.fullmatch(cik):
            raise ValueError("CIK must contain 1-10 digits")
        if not ACCESSION_PATTERN.fullmatch(filing.accession_number):
            raise ValueError("accession number has invalid format")
        if not DOCUMENT_PATTERN.fullmatch(filing.primary_document):
            raise ValueError("primary document has invalid filename")

        compact_accession = filing.accession_number.replace("-", "")
        base_url = self.settings.base_url.rstrip("/")
        return (
            f"{base_url}/Archives/edgar/data/{cik}/"
            f"{compact_accession}/{filing.primary_document}"
        )
