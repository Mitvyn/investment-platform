from __future__ import annotations

import re
import uuid
from typing import Any, Mapping

from workers.sec.storage import (
    EvidenceStorageError,
    JsonTransport,
    SupabaseStorageSettings,
    UrllibJsonTransport,
)

from .worker import SecurityJobClaim

TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ERROR_STAGES = {"security_registry", "market_fetch", "persistence", "worker"}


class SupabaseSecurityJobStore:
    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)

    def _rpc(self, name: str, payload: Mapping[str, Any]) -> Any:
        response = self.transport.request_json(
            "POST",
            f"{self.settings.url.rstrip('/')}/rest/v1/rpc/{name}",
            headers={
                "Content-Type": "application/json",
                "apikey": self.settings.secret_key,
            },
            payload=payload,
        )
        if not 200 <= response.status < 300:
            raise EvidenceStorageError(
                f"security job store returned HTTP {response.status} for {name}"
            )
        return response.payload

    def claim_next(self, worker_id: str) -> SecurityJobClaim | None:
        payload = self._rpc(
            "iros_claim_security_job",
            {"selected_worker_id": worker_id},
        )
        if not isinstance(payload, list):
            raise EvidenceStorageError("security job claim response is invalid")
        if not payload:
            return None
        if len(payload) != 1 or not isinstance(payload[0], dict):
            raise EvidenceStorageError("security job claim count is invalid")
        row = payload[0]
        try:
            job_id = _uuid_text(row["job_id"])
            operator_id = _uuid_text(row["operator_id"])
            ticker = str(row["ticker"])
            attempt_id = _uuid_text(row["attempt_id"])
            attempt_number = int(row["attempt_number"])
            lease_token = _uuid_text(row["lease_token"])
        except (KeyError, TypeError, ValueError) as error:
            raise EvidenceStorageError("security job claim is malformed") from error
        if not TICKER_PATTERN.fullmatch(ticker) or attempt_number not in (1, 2):
            raise EvidenceStorageError("security job claim is malformed")
        return SecurityJobClaim(
            job_id=job_id,
            operator_id=operator_id,
            ticker=ticker,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            lease_token=lease_token,
        )

    def complete(
        self,
        claim: SecurityJobClaim,
        *,
        security_id: str,
        market_series_id: str,
    ) -> None:
        self._rpc(
            "iros_complete_security_job",
            {
                "selected_job_id": _uuid_text(claim.job_id),
                "selected_attempt_id": _uuid_text(claim.attempt_id),
                "selected_lease_token": _uuid_text(claim.lease_token),
                "selected_security_id": _uuid_text(security_id),
                "selected_market_series_id": _uuid_text(market_series_id),
            },
        )

    def fail(
        self,
        claim: SecurityJobClaim,
        *,
        stage: str,
        error_code: str,
        retryable: bool,
    ) -> None:
        if stage not in ERROR_STAGES or not ERROR_CODE_PATTERN.fullmatch(error_code):
            raise ValueError("security job failure classification is invalid")
        self._rpc(
            "iros_fail_security_job",
            {
                "selected_job_id": _uuid_text(claim.job_id),
                "selected_attempt_id": _uuid_text(claim.attempt_id),
                "selected_lease_token": _uuid_text(claim.lease_token),
                "selected_error_stage": stage,
                "selected_error_code": error_code,
                "selected_retryable": retryable,
            },
        )


def _uuid_text(value: object) -> str:
    text = str(value)
    uuid.UUID(text)
    return text
