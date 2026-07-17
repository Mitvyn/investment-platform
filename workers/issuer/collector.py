from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Mapping, Protocol

from .models import CollectedRelease, ReleaseRequest


_STATUS_MARKER = b"\n__IROS_HTTP_STATUS__:"


class IssuerCollectorError(RuntimeError):
    """Raised when an official issuer release cannot be collected."""


@dataclass(frozen=True, slots=True)
class IssuerSettings:
    timeout_seconds: float = 15.0
    max_attempts: int = 2

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("issuer timeout must be positive")
        if self.max_attempts <= 0:
            raise ValueError("issuer attempts must be positive")


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


class CurlBytesTransport:
    def __init__(self, timeout_seconds: float, max_attempts: int = 2) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> BytesResponse:
        command = [
            "curl",
            "--location",
            "--silent",
            "--show-error",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--max-time",
            str(self.timeout_seconds),
            "--write-out",
            f"{_STATUS_MARKER.decode()}%{{http_code}}",
        ]
        for name, value in headers.items():
            command.extend(("--header", f"{name}: {value}"))
        command.extend(("--url", url))

        for _ in range(self.max_attempts):
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    check=False,
                    timeout=self.timeout_seconds + 5,
                )
            except subprocess.TimeoutExpired:
                continue
            except OSError as error:
                raise IssuerCollectorError(
                    "issuer curl transport is unavailable"
                ) from error

            if result.returncode == 28:
                continue
            if result.returncode != 0:
                raise IssuerCollectorError("could not reach issuer site")

            body, marker, status_bytes = result.stdout.rpartition(_STATUS_MARKER)
            if not marker or len(status_bytes) != 3 or not status_bytes.isdigit():
                raise IssuerCollectorError(
                    "issuer site returned an invalid HTTP response"
                )
            return BytesResponse(
                body=body,
                status=int(status_bytes),
                headers={},
            )

        raise IssuerCollectorError(
            f"issuer site timed out after {self.max_attempts} attempts"
        )


class IssuerCollector:
    def __init__(
        self,
        settings: IssuerSettings | None = None,
        *,
        transport: BytesTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or IssuerSettings()
        self.transport = transport or CurlBytesTransport(
            self.settings.timeout_seconds,
            self.settings.max_attempts,
        )
        self.clock = clock or (lambda: datetime.now(UTC))

    def fetch_release(self, release: ReleaseRequest) -> CollectedRelease:
        response = self.transport.request(
            release.source_url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
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
