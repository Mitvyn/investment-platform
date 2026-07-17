from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from workers.http import trusted_ssl_context

from .models import EvidenceTrace


class EvidenceStorageError(RuntimeError):
    """Raised when evidence cannot be persisted."""


@dataclass(frozen=True, slots=True)
class JsonResponse:
    payload: Any
    status: int
    headers: Mapping[str, str]


class JsonTransport(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> JsonResponse: ...


class UrllibJsonTransport:
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self.ssl_context = trusted_ssl_context()

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> JsonResponse:
        request = Request(
            url,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=dict(headers),
            method=method,
        )
        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
                context=self.ssl_context,
            ) as response:
                raw = response.read()
                decoded = json.loads(raw.decode()) if raw else None
                return JsonResponse(
                    payload=decoded,
                    status=response.status,
                    headers=dict(response.headers.items()),
                )
        except HTTPError as error:
            raise EvidenceStorageError(
                f"evidence store returned HTTP {error.code}"
            ) from error
        except URLError as error:
            raise EvidenceStorageError("could not reach evidence store") from error


@dataclass(frozen=True, slots=True)
class SupabaseStorageSettings:
    url: str
    secret_key: str
    timeout_seconds: float = 20.0


class SupabaseEvidenceStore:
    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)

    def persist(self, trace: EvidenceTrace) -> None:
        for table, record in self._records(trace):
            query = urlencode({"on_conflict": "id"})
            url = f"{self.settings.url.rstrip('/')}/rest/v1/{table}?{query}"
            response = self.transport.request_json(
                "POST",
                url,
                headers={
                    "Content-Type": "application/json",
                    "Prefer": "resolution=ignore-duplicates,return=minimal",
                    "apikey": self.settings.secret_key,
                },
                payload=record,
            )
            if response.status not in (200, 201, 204):
                raise EvidenceStorageError(
                    f"evidence store returned HTTP {response.status} for {table}"
                )

    def verify(self, trace: EvidenceTrace) -> dict[str, str]:
        verified: dict[str, str] = {}
        for table, record in self._records(trace):
            expected = {
                key: value
                for key, value in record.items()
                if key
                not in {
                    "finished_at",
                    "retrieved_at",
                    "started_at",
                    "verified_at",
                }
            }
            query = urlencode(
                {
                    "id": f"eq.{record['id']}",
                    "operator_id": f"eq.{trace.operator_id}",
                    "select": ",".join(expected),
                }
            )
            url = f"{self.settings.url.rstrip('/')}/rest/v1/{table}?{query}"
            response = self.transport.request_json(
                "GET",
                url,
                headers={
                    "apikey": self.settings.secret_key,
                },
            )
            if response.status != 200:
                raise EvidenceStorageError(
                    f"evidence store returned HTTP {response.status} for {table}"
                )
            if not isinstance(response.payload, list) or len(response.payload) != 1:
                raise EvidenceStorageError(
                    f"expected exactly one hosted row for {table}"
                )
            if response.payload[0] != expected:
                raise EvidenceStorageError(
                    f"hosted row does not match expected evidence for {table}"
                )
            verified[table] = record["id"]

        return verified

    @staticmethod
    def _records(
        trace: EvidenceTrace,
    ) -> list[tuple[str, dict[str, Any]]]:
        return [
            (
                "iros_research_runs",
                {
                    "id": trace.research_run_id,
                    "operator_id": trace.operator_id,
                    "ticker": trace.ticker,
                    "run_type": "sec_filing",
                    "trigger_type": "manual",
                    "status": trace.run_status,
                    "idempotency_key": trace.idempotency_key,
                    "started_at": trace.retrieved_at,
                    "finished_at": trace.retrieved_at,
                },
            ),
            (
                "iros_sources",
                {
                    "id": trace.source_id,
                    "operator_id": trace.operator_id,
                    "provider": trace.source_provider,
                    "external_id": trace.source_external_id,
                    "source_type": "filing",
                    "title": trace.source_title,
                    "canonical_url": trace.source_canonical_url,
                    "retrieved_at": trace.retrieved_at,
                },
            ),
            (
                "iros_source_documents",
                {
                    "id": trace.document_id,
                    "operator_id": trace.operator_id,
                    "source_id": trace.source_id,
                    "research_run_id": trace.research_run_id,
                    "accession_number": trace.accession_number,
                    "filing_form": trace.filing_form,
                    "filed_at": trace.filed_at,
                    "period_end": trace.period_end,
                    "primary_document": trace.primary_document,
                    "source_url": trace.source_url,
                    "content_sha256": trace.content_sha256,
                    "retrieved_at": trace.retrieved_at,
                },
            ),
            (
                "iros_source_passages",
                {
                    "id": trace.passage_id,
                    "operator_id": trace.operator_id,
                    "document_id": trace.document_id,
                    "research_run_id": trace.research_run_id,
                    "locator": trace.locator,
                    "passage_text": trace.passage_text,
                    "passage_sha256": trace.passage_sha256,
                },
            ),
            (
                "iros_claims",
                {
                    "id": trace.claim_id,
                    "operator_id": trace.operator_id,
                    "research_run_id": trace.research_run_id,
                    "ticker": trace.ticker,
                    "company_name": trace.company_name,
                    "claim_text": trace.claim_text,
                    "claim_sha256": trace.claim_sha256,
                    "verification_state": trace.verification_state,
                    "verified_at": trace.retrieved_at,
                },
            ),
            (
                "iros_claim_evidence",
                {
                    "id": trace.claim_evidence_id,
                    "operator_id": trace.operator_id,
                    "claim_id": trace.claim_id,
                    "passage_id": trace.passage_id,
                    "relationship": trace.relationship,
                },
            ),
        ]
