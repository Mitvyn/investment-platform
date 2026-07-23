from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Callable

from workers.ids import stable_id
from workers.sec.collector import BytesTransport, SecSettings, UrllibBytesTransport

from .models import RegisteredSecurity

TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")


class SecurityRegistryError(RuntimeError):
    """Raised when SEC security identity cannot be resolved exactly."""


class SecurityRegistryClient:
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

    def resolve(self, ticker: str, *, operator_id: str) -> RegisteredSecurity:
        uuid.UUID(operator_id)
        normalized_ticker = ticker.strip().upper()
        if not TICKER_PATTERN.fullmatch(normalized_ticker):
            raise ValueError("ticker has invalid format")
        source_url = (
            f"{self.settings.base_url.rstrip('/')}/files/company_tickers_exchange.json"
        )
        response = self.transport.request(
            source_url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.settings.user_agent,
            },
        )
        if not 200 <= response.status < 300:
            raise SecurityRegistryError(
                f"SEC returned HTTP {response.status} for security registry"
            )
        try:
            payload = json.loads(response.body.decode("utf-8"))
            fields = payload["fields"]
            data = payload["data"]
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SecurityRegistryError("SEC security registry is malformed") from error
        if fields != ["cik", "name", "ticker", "exchange"] or not isinstance(
            data, list
        ):
            raise SecurityRegistryError("SEC security registry schema is unsupported")

        matches = [
            row
            for row in data
            if isinstance(row, list)
            and len(row) == 4
            and str(row[2]).strip().upper() == normalized_ticker
        ]
        if len(matches) != 1:
            raise SecurityRegistryError(
                "SEC security registry must contain exactly one ticker match"
            )
        cik_value, issuer_name, resolved_ticker, exchange = matches[0]
        try:
            cik = str(int(cik_value)).zfill(10)
        except (TypeError, ValueError) as error:
            raise SecurityRegistryError("SEC security CIK is invalid") from error
        issuer = str(issuer_name).strip()
        venue = str(exchange).strip()
        if not issuer or not venue:
            raise SecurityRegistryError("SEC security identity is incomplete")
        if str(resolved_ticker).strip().upper() != normalized_ticker:
            raise SecurityRegistryError("SEC returned a different ticker")

        return RegisteredSecurity(
            operator_id=operator_id,
            security_id=stable_id(
                operator_id,
                "security",
                f"sec-cik:{cik}",
            ),
            cik=cik,
            issuer_name=issuer,
            ticker=normalized_ticker,
            primary_listing_exchange=venue,
            source_url=source_url,
            retrieved_at=self.clock().astimezone(UTC).isoformat(),
            response_sha256=hashlib.sha256(response.body).hexdigest(),
        )
