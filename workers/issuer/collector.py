from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from workers.http import trusted_ssl_context

from .models import CollectedRelease, ReleaseRequest


class IssuerCollectorError(RuntimeError):
    """Raised when an official issuer release cannot be collected."""


@dataclass(frozen=True, slots=True)
class IssuerSettings:
    user_agent: str = "Investment-Research-OS/0.2"
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.user_agent.strip():
            raise ValueError("issuer user agent cannot be blank")


@dataclass(frozen=True, slots=True)
class BytesResponse:
    body: bytes
    status: int
    headers: Mapping[str, str]


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
                )
        except HTTPError as error:
            raise IssuerCollectorError(
                f"issuer site returned HTTP {error.code}"
            ) from error
        except URLError as error:
            raise IssuerCollectorError("could not reach issuer site") from error


class IssuerCollector:
    def __init__(
        self,
        settings: IssuerSettings | None = None,
        *,
        transport: BytesTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or IssuerSettings()
        self.transport = transport or UrllibBytesTransport(
            self.settings.timeout_seconds
        )
        self.clock = clock or (lambda: datetime.now(UTC))

    def fetch_release(self, release: ReleaseRequest) -> CollectedRelease:
        response = self.transport.request(
            release.source_url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": self.settings.user_agent,
            },
        )
        if not 200 <= response.status < 300:
            raise IssuerCollectorError(
                f"issuer site returned HTTP {response.status}"
            )
        try:
            html = response.body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise IssuerCollectorError("issuer release was not valid UTF-8") from error

        return CollectedRelease(
            request=release,
            retrieved_at=self.clock().astimezone(UTC).isoformat(),
            html=html,
            content_sha256=hashlib.sha256(response.body).hexdigest(),
        )
