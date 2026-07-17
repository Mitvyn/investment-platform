from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from workers.sec.storage import (
    EvidenceStorageError,
    JsonTransport,
    SupabaseStorageSettings,
    UrllibJsonTransport,
)

from .models import IssuerContext


def _verification_values_match(
    field: str,
    hosted: Any,
    expected: Any,
) -> bool:
    if field != "published_at":
        return hosted == expected
    if not isinstance(hosted, str) or not isinstance(expected, str):
        return False
    try:
        hosted_at = datetime.fromisoformat(hosted.replace("Z", "+00:00"))
        expected_at = datetime.fromisoformat(expected.replace("Z", "+00:00"))
    except ValueError:
        return False
    return hosted_at == expected_at


class SupabaseIssuerStore:
    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)

    def persist(self, context: IssuerContext) -> None:
        for table, record in self._records(context):
            url = (
                f"{self.settings.url.rstrip('/')}/rest/v1/{table}?"
                f"{urlencode({'on_conflict': 'id'})}"
            )
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
                    f"issuer context store returned HTTP {response.status} for {table}"
                )

    def verify(self, context: IssuerContext) -> dict[str, list[str]]:
        verified: dict[str, list[str]] = {}
        for table, record in self._records(context):
            expected = {
                key: value
                for key, value in record.items()
                if key not in {"finished_at", "retrieved_at", "started_at"}
            }
            query = urlencode(
                {
                    "id": f"eq.{record['id']}",
                    "operator_id": f"eq.{context.operator_id}",
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
                    f"issuer context store returned HTTP {response.status} for {table}"
                )
            if not isinstance(response.payload, list) or len(response.payload) != 1:
                raise EvidenceStorageError(
                    f"expected exactly one hosted row for {table} id {record['id']}"
                )
            hosted = response.payload[0]
            mismatched_fields = sorted(
                key
                for key, value in expected.items()
                if key not in hosted
                or not _verification_values_match(
                    key,
                    hosted[key],
                    value,
                )
            )
            if mismatched_fields:
                raise EvidenceStorageError(
                    f"hosted row does not match issuer context for {table}; "
                    f"mismatched fields: {', '.join(mismatched_fields)}"
                )
            verified.setdefault(table, []).append(record["id"])
        return verified

    @staticmethod
    def _records(context: IssuerContext) -> list[tuple[str, dict[str, Any]]]:
        records: list[tuple[str, dict[str, Any]]] = [
            (
                "iros_research_runs",
                {
                    "id": context.research_run_id,
                    "operator_id": context.operator_id,
                    "ticker": context.ticker,
                    "run_type": "issuer_release",
                    "trigger_type": "manual",
                    "status": context.run_status,
                    "idempotency_key": context.idempotency_key,
                    "started_at": context.retrieved_at,
                    "finished_at": context.retrieved_at,
                },
            ),
            (
                "iros_issuer_releases",
                {
                    "id": context.release_id,
                    "operator_id": context.operator_id,
                    "research_run_id": context.research_run_id,
                    "ticker": context.ticker,
                    "company_name": context.company_name,
                    "release_type": context.release_type,
                    "title": context.title,
                    "published_at": context.published_at,
                    "source_url": context.source_url,
                    "retrieved_at": context.retrieved_at,
                    "content_sha256": context.content_sha256,
                },
            ),
        ]
        records.extend(
            (
                "iros_issuer_passages",
                {
                    "id": passage.id,
                    "operator_id": context.operator_id,
                    "issuer_release_id": context.release_id,
                    "research_run_id": context.research_run_id,
                    "locator": passage.locator,
                    "passage_text": passage.passage_text,
                    "passage_sha256": passage.passage_sha256,
                },
            )
            for passage in context.passages
        )
        records.extend(
            (
                "iros_financial_metrics",
                {
                    "id": metric.id,
                    "operator_id": context.operator_id,
                    "research_run_id": context.research_run_id,
                    "issuer_release_id": context.release_id,
                    "passage_id": metric.passage_id,
                    "ticker": context.ticker,
                    "metric_key": metric.metric_key,
                    "metric_label": metric.metric_label,
                    "metric_kind": metric.metric_kind,
                    "value": metric.value,
                    "unit": metric.unit,
                    "source_period": metric.source_period,
                    "comparison_period": metric.comparison_period,
                    "formula": metric.formula,
                },
            )
            for metric in context.metrics
        )
        records.extend(
            (
                "iros_catalysts",
                {
                    "id": catalyst.id,
                    "operator_id": context.operator_id,
                    "research_run_id": context.research_run_id,
                    "issuer_release_id": context.release_id,
                    "passage_id": catalyst.passage_id,
                    "ticker": context.ticker,
                    "title": catalyst.title,
                    "status": catalyst.status,
                    "window_start": catalyst.window_start,
                    "window_end": catalyst.window_end,
                },
            )
            for catalyst in context.catalysts
        )
        records.extend(
            (
                "iros_risks",
                {
                    "id": risk.id,
                    "operator_id": context.operator_id,
                    "research_run_id": context.research_run_id,
                    "issuer_release_id": context.release_id,
                    "passage_id": risk.passage_id,
                    "ticker": context.ticker,
                    "title": risk.title,
                    "risk_type": risk.risk_type,
                    "severity": risk.severity,
                    "status": risk.status,
                },
            )
            for risk in context.risks
        )
        return records
