from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from curl_cffi import requests

from workers.sec.collector import BytesResponse


class PrimarySourceHttpError(RuntimeError):
    """Raised when a primary-source HTTP request cannot complete."""


class _Response(Protocol):
    content: bytes
    status_code: int
    headers: Mapping[str, str]
    url: str


class _Session(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        allow_redirects: bool,
    ) -> _Response: ...


class CurlCffiBytesTransport:
    """Source-neutral pooled transport for live primary-source acquisition."""

    def __init__(
        self,
        timeout_seconds: float,
        *,
        session: _Session | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("source request timeout must be positive")
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> BytesResponse:
        try:
            response = self._session.get(
                url,
                headers=dict(headers),
                timeout=self._timeout_seconds,
                allow_redirects=True,
            )
        except requests.RequestsError as error:
            raise PrimarySourceHttpError(
                "primary source request failed"
            ) from error
        return BytesResponse(
            body=response.content,
            status=response.status_code,
            headers=dict(response.headers),
            final_url=response.url,
        )


__all__ = ["CurlCffiBytesTransport", "PrimarySourceHttpError"]
