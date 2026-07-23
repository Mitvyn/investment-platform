from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
import hashlib
from typing import Any, Mapping
from urllib.parse import urlencode

from investment_research_os.ids import stable_id
from investment_research_os.research_runs import (
    EligibilityCheck,
    EligibilityResult,
    SecurityIdentity,
)
from workers.sec.storage import (
    EvidenceStorageError,
    JsonTransport,
    SupabaseStorageSettings,
    UrllibJsonTransport,
)

from . import (
    CatalystSnapshot,
    EvidenceBundle,
    EvidenceGap,
    EvidenceItem,
    RiskSnapshot,
    VerifiedMetricSnapshot,
)


class SupabaseEvidenceBundleRepository:
    """Persists one immutable, owner-scoped bundle and its run link."""

    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)

    def save(self, bundle: EvidenceBundle) -> EvidenceBundle:
        existing = self.get_for_run(bundle.operator_id, bundle.research_run_id)
        if existing is not None:
            return self._require_exact_match(existing, bundle)

        for table, conflict_columns, record in self._records(bundle):
            self._insert(table, conflict_columns, record)
        self._finalize(bundle)
        self._insert(
            "iros_research_run_evidence_bundles",
            "operator_id,research_run_id",
            {
                "operator_id": bundle.operator_id,
                "research_run_id": bundle.research_run_id,
                "bundle_id": bundle.id,
                "linked_at": bundle.created_at.isoformat(),
            },
        )
        persisted = self.get_for_run(bundle.operator_id, bundle.research_run_id)
        if persisted is None:
            raise EvidenceStorageError("persisted evidence bundle is unavailable")
        return self._require_exact_match(persisted, bundle)

    def get(self, operator_id: str, bundle_id: str) -> EvidenceBundle | None:
        return self._get_one(
            {
                "operator_id": f"eq.{operator_id}",
                "bundle_id": f"eq.{bundle_id}",
            }
        )

    def get_for_run(
        self,
        operator_id: str,
        research_run_id: str,
    ) -> EvidenceBundle | None:
        return self._get_one(
            {
                "operator_id": f"eq.{operator_id}",
                "research_run_id": f"eq.{research_run_id}",
            }
        )

    def _get_one(self, filters: Mapping[str, str]) -> EvidenceBundle | None:
        query = urlencode({**filters, "select": "canonical_bundle"})
        response = self.transport.request_json(
            "GET",
            (
                f"{self.settings.url.rstrip('/')}/rest/v1/"
                f"iros_v_research_run_evidence_bundle?{query}"
            ),
            headers={"apikey": self.settings.secret_key},
        )
        if response.status != 200:
            raise EvidenceStorageError(
                "evidence bundle store returned "
                f"HTTP {response.status} for composed bundle view"
            )
        if not isinstance(response.payload, list):
            raise EvidenceStorageError("evidence bundle view returned invalid payload")
        if not response.payload:
            return None
        if len(response.payload) != 1 or not isinstance(response.payload[0], dict):
            raise EvidenceStorageError("evidence bundle view returned duplicate rows")
        payload = response.payload[0].get("canonical_bundle")
        if not isinstance(payload, dict):
            raise EvidenceStorageError("evidence bundle view returned invalid contract")
        try:
            bundle = _bundle_from_wire(payload)
        except (KeyError, TypeError, ValueError) as error:
            raise EvidenceStorageError(
                "evidence bundle view returned invalid contract"
            ) from error
        bundle = self._hydrate_passages(bundle)
        if bundle.as_dict() != payload:
            raise EvidenceStorageError(
                "evidence bundle view returned non-canonical contract"
            )
        return bundle

    def _hydrate_passages(self, bundle: EvidenceBundle) -> EvidenceBundle:
        query = urlencode(
            {
                "operator_id": f"eq.{bundle.operator_id}",
                "bundle_id": f"eq.{bundle.id}",
                "item_kind": "eq.passage",
                "select": (
                    "ordinal,item_id,item_version_id,item_kind,"
                    "canonical_payload"
                ),
                "order": "ordinal.asc",
            }
        )
        response = self.transport.request_json(
            "GET",
            (
                f"{self.settings.url.rstrip('/')}/rest/v1/"
                f"iros_v_evidence_bundle_manifest?{query}"
            ),
            headers={"apikey": self.settings.secret_key},
        )
        if response.status != 200 or not isinstance(response.payload, list):
            raise EvidenceStorageError(
                "evidence passage store returned invalid payload"
            )
        payload_by_version: dict[str, Mapping[str, Any]] = {}
        for row in response.payload:
            if not isinstance(row, dict):
                raise EvidenceStorageError(
                    "evidence passage store returned invalid payload"
                )
            version_id = row.get("item_version_id")
            canonical_payload = row.get("canonical_payload")
            if (
                not isinstance(version_id, str)
                or not isinstance(canonical_payload, dict)
                or version_id in payload_by_version
            ):
                raise EvidenceStorageError(
                    "evidence passage store returned invalid payload"
                )
            payload_by_version[version_id] = canonical_payload

        hydrated: list[EvidenceItem] = []
        for item in bundle.manifest:
            if item.item_kind != "passage":
                hydrated.append(item)
                continue
            passage = payload_by_version.get(item.evidence_version_id, {})
            if not passage:
                hydrated.append(item)
                continue
            passage_id = passage.get("passage_id")
            passage_text = passage.get("passage_text")
            passage_hash = passage.get("passage_sha256")
            if (
                passage.get("contract_version") != "evidence_passage.v1"
                or passage.get("evidence_id") != item.evidence_id
                or not isinstance(passage_id, str)
                or not isinstance(passage_text, str)
                or not passage_text
                or not isinstance(passage_hash, str)
                or hashlib.sha256(passage_text.encode()).hexdigest()
                != passage_hash
                or passage_hash != item.content_hash
            ):
                raise EvidenceStorageError(
                    "evidence passage payload failed integrity validation"
                )
            hydrated.append(
                replace(
                    item,
                    passage_id=passage_id,
                    passage_hash=passage_hash,
                    passage_text=passage_text,
                )
            )
        return replace(bundle, manifest=tuple(hydrated))

    def _insert(
        self,
        table: str,
        conflict_columns: str,
        record: Mapping[str, Any],
    ) -> None:
        query = urlencode({"on_conflict": conflict_columns})
        response = self.transport.request_json(
            "POST",
            f"{self.settings.url.rstrip('/')}/rest/v1/{table}?{query}",
            headers={
                "Content-Type": "application/json",
                "Prefer": "resolution=ignore-duplicates,return=minimal",
                "apikey": self.settings.secret_key,
            },
            payload=record,
        )
        if response.status not in (200, 201, 204):
            raise EvidenceStorageError(
                f"evidence bundle store returned HTTP {response.status} for {table}"
            )

    def _finalize(self, bundle: EvidenceBundle) -> None:
        query = urlencode(
            {
                "id": f"eq.{bundle.id}",
                "operator_id": f"eq.{bundle.operator_id}",
                "persistence_state": "eq.draft",
            }
        )
        response = self.transport.request_json(
            "PATCH",
            f"{self.settings.url.rstrip('/')}/rest/v1/iros_evidence_bundles?{query}",
            headers={
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
                "apikey": self.settings.secret_key,
            },
            payload={"persistence_state": "complete"},
        )
        if response.status not in (200, 204):
            raise EvidenceStorageError(
                "evidence bundle store returned "
                f"HTTP {response.status} while finalizing iros_evidence_bundles"
            )

    @staticmethod
    def _require_exact_match(
        persisted: EvidenceBundle,
        requested: EvidenceBundle,
    ) -> EvidenceBundle:
        def passage_signature(bundle: EvidenceBundle):
            return tuple(
                (
                    item.evidence_id,
                    item.evidence_version_id,
                    item.passage_id,
                    item.passage_hash,
                    item.passage_text,
                )
                for item in bundle.manifest
                if item.item_kind == "passage"
            )

        if (
            persisted.as_dict() != requested.as_dict()
            or passage_signature(persisted) != passage_signature(requested)
        ):
            raise EvidenceStorageError(
                "persisted evidence bundle does not match requested contract"
            )
        return persisted

    @staticmethod
    def _records(
        bundle: EvidenceBundle,
    ) -> list[tuple[str, str, Mapping[str, Any]]]:
        wire = bundle.as_dict()
        snapshots = {
            snapshot["id"]: snapshot
            for collection in ("verified_metrics", "catalysts", "risks")
            for snapshot in wire[collection]
        }
        records: list[tuple[str, str, Mapping[str, Any]]] = []
        for item, manifest in zip(bundle.manifest, wire["manifest"], strict=True):
            canonical_payload = snapshots.get(item.evidence_id, {})
            if item.item_kind == "passage":
                canonical_payload = {
                    "contract_version": "evidence_passage.v1",
                    "evidence_id": item.evidence_id,
                    "passage_id": item.passage_id,
                    "passage_text": item.passage_text,
                    "passage_sha256": item.passage_hash,
                }
            records.append(
                (
                    "iros_evidence_versions",
                    "operator_id,item_id,item_version_id",
                    {
                        "id": item.evidence_version_id,
                        "operator_id": bundle.operator_id,
                        "security_id": bundle.security_id,
                        "item_id": manifest["item_id"],
                        "item_version_id": manifest["item_version_id"],
                        "provenance_type": "primary_source",
                        "item_kind": manifest["item_kind"],
                        "source_class": manifest["source_class"],
                        "source_locator": manifest["source_locator"],
                        "locator": manifest["locator"],
                        "content_sha256": manifest["content_sha256"],
                        "published_at": manifest["published_at"],
                        "retrieved_at": manifest["retrieved_at"],
                        "effective_at": manifest["effective_at"],
                        "filing_period_start": manifest["filing_period_start"],
                        "filing_period_end": manifest["filing_period_end"],
                        "freshness_state": manifest["freshness_state"],
                        "freshness_reason_code": manifest[
                            "freshness_reason_code"
                        ],
                        "freshness_policy_version": manifest[
                            "freshness_policy_version"
                        ],
                        "canonical_payload": canonical_payload,
                        "created_at": bundle.created_at.isoformat(),
                    },
                )
            )
        records.append(
            (
                "iros_evidence_bundles",
                "operator_id,bundle_hash",
                {
                    "id": bundle.id,
                    "operator_id": bundle.operator_id,
                    "security_id": bundle.security_id,
                    "security_identity": wire["security_identity"],
                    "as_of_cutoff": wire["as_of_cutoff"],
                    "bundle_hash": wire["bundle_hash"],
                    "eligibility": wire["eligibility"],
                    "evidence_policy_version": wire["evidence_policy_version"],
                    "freshness_policy_version": wire["freshness_policy_version"],
                    "grader_ready": wire["grader_ready"],
                    "manifest_count": len(bundle.manifest),
                    "gap_count": len(bundle.gaps),
                    "persistence_state": "draft",
                    "created_at": wire["created_at"],
                },
            )
        )
        records.extend(
            (
                "iros_evidence_bundle_items",
                "operator_id,bundle_id,ordinal",
                {
                    "id": stable_id(
                        bundle.operator_id,
                        "evidence-bundle-item",
                        f"{bundle.id}:{ordinal}",
                    ),
                    "operator_id": bundle.operator_id,
                    "bundle_id": bundle.id,
                    "evidence_version_id": item.evidence_version_id,
                    "ordinal": ordinal,
                    "created_at": bundle.created_at.isoformat(),
                },
            )
            for ordinal, item in enumerate(bundle.manifest, start=1)
        )
        records.extend(
            (
                "iros_evidence_bundle_gaps",
                "operator_id,bundle_id,gap_id",
                {
                    "operator_id": bundle.operator_id,
                    "bundle_id": bundle.id,
                    "gap_id": gap["gap_id"],
                    "requirement_id": gap["requirement_id"],
                    "source_class": gap["source_class"],
                    "reason_code": gap["reason_code"],
                    "explanation": gap["explanation"],
                    "blocking": True,
                    "created_at": bundle.created_at.isoformat(),
                },
            )
            for gap in wire["gaps"]
        )
        return records


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def _date(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def _bundle_from_wire(payload: Mapping[str, Any]) -> EvidenceBundle:
    if payload["contract_version"] != "evidence_bundle.v1":
        raise ValueError("unsupported evidence bundle contract")
    identity = payload["security_identity"]
    eligibility = payload["eligibility"]
    if not isinstance(identity, dict) or not isinstance(eligibility, dict):
        raise TypeError("invalid evidence bundle object")
    manifest = tuple(
        EvidenceItem(
            evidence_id=item["item_id"],
            evidence_version_id=item["item_version_id"],
            provenance_type="primary_source",
            item_kind=item["item_kind"],
            source_class=item["source_class"],
            source_locator=item["locator"],
            canonical_url=item["source_locator"],
            publication_at=_timestamp(item["published_at"]),
            retrieved_at=_timestamp(item["retrieved_at"]),
            effective_at=_timestamp(item["effective_at"]),
            filing_period_start=_date(item["filing_period_start"]),
            filing_period_end=_date(item["filing_period_end"]),
            content_hash=item["content_sha256"],
            passage_id=None,
            passage_hash=None,
            freshness=item["freshness_state"],
        )
        for item in payload["manifest"]
    )
    return EvidenceBundle(
        id=payload["id"],
        operator_id=payload["operator_id"],
        research_run_id=payload["research_run_id"],
        security_id=payload["security_id"],
        security_identity=SecurityIdentity(
            id=identity["id"],
            cik=identity["cik"],
            issuer_name=identity["issuer_name"],
            symbol=identity["symbol"],
            primary_listing_exchange=identity["primary_listing_exchange"],
        ),
        as_of_cutoff=_timestamp(payload["as_of_cutoff"]),
        content_hash=payload["bundle_hash"],
        manifest=manifest,
        metrics=tuple(
            VerifiedMetricSnapshot(
                snapshot_id=item["id"],
                metric_key=item["metric_key"],
                value=item["value"],
                unit=item["unit"],
                period_start=_date(item["period_start"]),
                period_end=_date(item["period_end"]),
                calculation_method=item["calculation_method"],
                formula=item["formula"],
                supporting_evidence_ids=tuple(item["supporting_evidence_ids"]),
            )
            for item in payload["verified_metrics"]
        ),
        catalysts=tuple(
            CatalystSnapshot(
                snapshot_id=item["id"],
                program=item["program"],
                event=item["event"],
                basis=item["basis"],
                status=item["status"],
                window_start=_date(item["window_start"]),
                window_end=_date(item["window_end"]),
                supporting_evidence_ids=tuple(item["supporting_evidence_ids"]),
            )
            for item in payload["catalysts"]
        ),
        risks=tuple(
            RiskSnapshot(
                snapshot_id=item["id"],
                title=item["title"],
                risk_type=item["risk_type"],
                severity=item["severity"],
                status=item["status"],
                supporting_evidence_ids=tuple(item["supporting_evidence_ids"]),
            )
            for item in payload["risks"]
        ),
        grader_ready=payload["grader_ready"],
        gaps=tuple(
            EvidenceGap(
                code=item["gap_id"],
                source_class=item["source_class"],
                blocking=True,
                explanation=item["explanation"],
            )
            for item in payload["gaps"]
        ),
        eligibility=EligibilityResult(
            policy_version=eligibility["policy_version"],
            eligible=eligibility["eligible"],
            checks=tuple(
                EligibilityCheck(
                    rule_id=item["rule_id"],
                    rule_version=item["rule_version"],
                    passed=item["passed"],
                    evidence_reference=item["evidence_reference"],
                    reason_code=item["reason_code"],
                    explanation=item["explanation"],
                    evaluated_at=_timestamp(item["evaluated_at"]),
                )
                for item in eligibility["checks"]
            ),
            evaluated_at=_timestamp(eligibility["evaluated_at"]),
        ),
        evidence_policy_version=payload["evidence_policy_version"],
        freshness_policy_version=payload["freshness_policy_version"],
        created_at=_timestamp(payload["created_at"]),
    )


__all__ = ["SupabaseEvidenceBundleRepository"]
