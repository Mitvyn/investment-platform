from __future__ import annotations

from urllib.parse import urlencode

from workers.sec.storage import (
    EvidenceStorageError,
    JsonTransport,
    SupabaseStorageSettings,
    UrllibJsonTransport,
)

from .models import RegisteredSecurity


class SupabaseSecurityRegistryStore:
    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)

    def persist(self, security: RegisteredSecurity) -> None:
        query = urlencode({"on_conflict": "operator_id,id"})
        url = f"{self.settings.url.rstrip('/')}/rest/v1/iros_securities?{query}"
        response = self.transport.request_json(
            "POST",
            url,
            headers={
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=minimal",
                "apikey": self.settings.secret_key,
            },
            payload={
                "operator_id": security.operator_id,
                "id": security.security_id,
                "cik": security.cik,
                "issuer_name": security.issuer_name,
                "symbol": security.ticker,
                "primary_listing_exchange": security.primary_listing_exchange,
                "updated_at": security.retrieved_at,
            },
        )
        if response.status not in (200, 201, 204):
            raise EvidenceStorageError(
                f"security registry store returned HTTP {response.status}"
            )
