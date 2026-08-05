from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlsplit

from investment_research_os.provider_input_token_preflight import (
    InputTokenPreflightCompletion,
    InputTokenPreflightReceipt,
    InputTokenPreflightStart,
)
from workers.sec.storage import (
    EvidenceStorageError,
    JsonTransport,
    SupabaseStorageSettings,
    UrllibJsonTransport,
)


class InputTokenPreflightStorageError(RuntimeError):
    """Raised when persistent preflight storage returns inconsistent state."""


class SupabaseInputTokenPreflightStore:
    """Maps token-preflight transitions onto narrow iros-only RPCs."""

    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        parsed = urlsplit(settings.url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise InputTokenPreflightStorageError(
                "preflight Supabase URL must use HTTPS"
            )
        if not settings.secret_key.strip():
            raise InputTokenPreflightStorageError(
                "preflight Supabase secret key is required"
            )
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)

    def begin(
        self,
        start: InputTokenPreflightStart,
    ) -> InputTokenPreflightReceipt:
        payload = self._rpc(
            "iros_begin_provider_input_token_preflight",
            {
                "p_operator_id": start.operator_id,
                "p_preflight": {
                    "id": start.preflight_id,
                    "research_run_id": start.research_run_id,
                    "attempt_kind": start.attempt_kind,
                    "attempt_id": start.attempt_id,
                    "execution_identity": start.execution_identity,
                    "request_hash": start.request_hash,
                    "provider": start.provider,
                    "model": start.model,
                    "input_payload_sha256": start.input_payload_sha256,
                    "input_token_cap": start.input_token_cap,
                    "started_at": start.started_at.isoformat(),
                },
                "p_sanitized_request": dict(start.request_payload),
            },
        )
        return _receipt(
            payload,
            operator_id=start.operator_id,
            preflight_id=start.preflight_id,
            expected_states={"pending"},
        )

    def complete(
        self,
        completion: InputTokenPreflightCompletion,
    ) -> InputTokenPreflightReceipt:
        payload = self._rpc(
            "iros_complete_provider_input_token_preflight",
            {
                "p_operator_id": completion.operator_id,
                "p_preflight_id": completion.preflight_id,
                "p_completion": {
                    "state": completion.state,
                    "input_tokens": completion.input_tokens,
                    "within_cap": completion.within_cap,
                    "error_code": completion.error_code,
                    "retryable": completion.retryable,
                    "completed_at": completion.completed_at.isoformat(),
                },
                "p_sanitized_response": (
                    None
                    if completion.response_payload is None
                    else dict(completion.response_payload)
                ),
            },
        )
        return _receipt(
            payload,
            operator_id=completion.operator_id,
            preflight_id=completion.preflight_id,
            expected_states={completion.state},
        )

    def _rpc(self, name: str, payload: Mapping[str, Any]) -> object:
        try:
            response = self.transport.request_json(
                "POST",
                f"{self.settings.url.rstrip('/')}/rest/v1/rpc/{name}",
                headers={
                    "Content-Type": "application/json",
                    "apikey": self.settings.secret_key,
                },
                payload=payload,
            )
        except EvidenceStorageError as error:
            raise InputTokenPreflightStorageError(
                f"preflight store failed for {name}"
            ) from error
        if not 200 <= response.status < 300:
            raise InputTokenPreflightStorageError(
                f"preflight store returned HTTP {response.status} for {name}"
            )
        return response.payload


def _receipt(
    payload: object,
    *,
    operator_id: str,
    preflight_id: str,
    expected_states: set[str],
) -> InputTokenPreflightReceipt:
    row = _one_row(payload)
    if (
        row.get("operator_id") != operator_id
        or row.get("preflight_id") != preflight_id
        or row.get("state") not in expected_states
        or not isinstance(row.get("reused"), bool)
    ):
        raise InputTokenPreflightStorageError("preflight persistence receipt mismatch")
    return InputTokenPreflightReceipt(
        preflight_id=preflight_id,
        state=str(row["state"]),
        reused=bool(row["reused"]),
    )


def _one_row(payload: object) -> Mapping[str, object]:
    if (
        not isinstance(payload, list)
        or len(payload) != 1
        or not isinstance(payload[0], Mapping)
    ):
        raise InputTokenPreflightStorageError(
            "preflight store returned malformed response"
        )
    return payload[0]


__all__ = [
    "InputTokenPreflightStorageError",
    "SupabaseInputTokenPreflightStore",
]
