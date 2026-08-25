"""Desktop-local durable persistence for the Evidence Bundle repository port.

`InMemoryEvidenceBundleRepository` cannot survive a worker restart and the
Supabase repository requires hosted access, so the desktop-local command path
had nowhere to keep the artifact its `evidence_bundle` stage produces. This
adapter satisfies the same `EvidenceBundleRepository` protocol using
owner-scoped immutable local files.

Two records are written per bundle: the bundle itself under `bundles/`, and a
run index under `runs/` that names it, so `get_for_run` needs no directory
scan. Every record carries a content hash over its own payload and is read
fail-closed: a record that no longer hashes to its stored value, names another
operator, or arrives through a symlink is refused rather than returned.

The stored payload is lossless, passage text included, because the bundle is
the artifact downstream stages consume. It carries no lease token, worker
identity, secret, filesystem archive path, provider payload, or prompt.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping

from investment_research_os.research_runs import (
    EligibilityCheck,
    EligibilityResult,
    SecurityIdentity,
)

from . import (
    CatalystSnapshot,
    EvidenceBundle,
    EvidenceBundleError,
    EvidenceGap,
    EvidenceItem,
    RiskSnapshot,
    VerifiedMetricSnapshot,
)


RECORD_CONTRACT_VERSION = "local_evidence_bundle_record.v1"
RUN_INDEX_CONTRACT_VERSION = "local_evidence_bundle_run_index.v1"


class LocalEvidenceBundleStorageError(ValueError):
    """Raised when durable local Evidence Bundle state violates its contract."""


def _canonical_uuid(value: object, label: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as error:
        raise LocalEvidenceBundleStorageError(f"{label} must be a UUID") from error


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise LocalEvidenceBundleStorageError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise LocalEvidenceBundleStorageError(f"{label} is invalid") from error
    if parsed.tzinfo is None:
        raise LocalEvidenceBundleStorageError(f"{label} must be timezone aware")
    return parsed.astimezone(UTC)


def _optional_timestamp(value: object, label: str) -> datetime | None:
    return None if value is None else _timestamp(value, label)


def _date(value: object, label: str) -> date:
    if not isinstance(value, str):
        raise LocalEvidenceBundleStorageError(f"{label} is invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise LocalEvidenceBundleStorageError(f"{label} is invalid") from error


def _optional_date(value: object, label: str) -> date | None:
    return None if value is None else _date(value, label)


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _wire_timestamp(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _wire_date(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _item_payload(item: EvidenceItem) -> dict[str, Any]:
    return {
        "canonical_url": item.canonical_url,
        "content_hash": item.content_hash,
        "effective_at": _wire_timestamp(item.effective_at),
        "evidence_id": item.evidence_id,
        "evidence_version_id": item.evidence_version_id,
        "filing_period_end": _wire_date(item.filing_period_end),
        "filing_period_start": _wire_date(item.filing_period_start),
        "freshness": item.freshness,
        "item_kind": item.item_kind,
        "passage_hash": item.passage_hash,
        "passage_id": item.passage_id,
        "passage_text": item.passage_text,
        "provenance_type": item.provenance_type,
        "publication_at": _wire_timestamp(item.publication_at),
        "retrieved_at": _wire_timestamp(item.retrieved_at),
        "source_class": item.source_class,
        "source_locator": item.source_locator,
    }


def _item_from_payload(payload: Mapping[str, Any]) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=str(payload["evidence_id"]),
        evidence_version_id=str(payload["evidence_version_id"]),
        provenance_type=str(payload["provenance_type"]),
        item_kind=str(payload["item_kind"]),
        source_class=str(payload["source_class"]),
        source_locator=str(payload["source_locator"]),
        canonical_url=str(payload["canonical_url"]),
        publication_at=_optional_timestamp(
            payload["publication_at"],
            "evidence publication timestamp",
        ),
        retrieved_at=_timestamp(
            payload["retrieved_at"],
            "evidence retrieval timestamp",
        ),
        effective_at=_optional_timestamp(
            payload["effective_at"],
            "evidence effective timestamp",
        ),
        filing_period_start=_optional_date(
            payload["filing_period_start"],
            "filing period start",
        ),
        filing_period_end=_optional_date(
            payload["filing_period_end"],
            "filing period end",
        ),
        content_hash=str(payload["content_hash"]),
        passage_id=_optional_text(payload["passage_id"]),
        passage_hash=_optional_text(payload["passage_hash"]),
        freshness=str(payload["freshness"]),
        passage_text=_optional_text(payload["passage_text"]),
    )


def _metric_payload(metric: VerifiedMetricSnapshot) -> dict[str, Any]:
    return {
        "calculation_method": metric.calculation_method,
        "formula": metric.formula,
        "metric_key": metric.metric_key,
        "period_end": _wire_date(metric.period_end),
        "period_start": _wire_date(metric.period_start),
        "snapshot_id": metric.snapshot_id,
        "supporting_evidence_ids": list(metric.supporting_evidence_ids),
        "unit": metric.unit,
        "value": metric.value,
    }


def _metric_from_payload(payload: Mapping[str, Any]) -> VerifiedMetricSnapshot:
    return VerifiedMetricSnapshot(
        snapshot_id=str(payload["snapshot_id"]),
        metric_key=str(payload["metric_key"]),
        value=str(payload["value"]),
        unit=str(payload["unit"]),
        period_start=_optional_date(payload["period_start"], "metric period start"),
        period_end=_optional_date(payload["period_end"], "metric period end"),
        calculation_method=str(payload["calculation_method"]),
        formula=_optional_text(payload["formula"]),
        supporting_evidence_ids=tuple(
            str(item) for item in payload["supporting_evidence_ids"]
        ),
    )


def _catalyst_payload(catalyst: CatalystSnapshot) -> dict[str, Any]:
    return {
        "basis": catalyst.basis,
        "event": catalyst.event,
        "program": catalyst.program,
        "snapshot_id": catalyst.snapshot_id,
        "status": catalyst.status,
        "supporting_evidence_ids": list(catalyst.supporting_evidence_ids),
        "window_end": catalyst.window_end.isoformat(),
        "window_start": catalyst.window_start.isoformat(),
    }


def _catalyst_from_payload(payload: Mapping[str, Any]) -> CatalystSnapshot:
    return CatalystSnapshot(
        snapshot_id=str(payload["snapshot_id"]),
        event=str(payload["event"]),
        program=str(payload["program"]),
        basis=str(payload["basis"]),
        status=str(payload["status"]),
        window_start=_date(payload["window_start"], "catalyst window start"),
        window_end=_date(payload["window_end"], "catalyst window end"),
        supporting_evidence_ids=tuple(
            str(item) for item in payload["supporting_evidence_ids"]
        ),
    )


def _risk_payload(risk: RiskSnapshot) -> dict[str, Any]:
    return {
        "risk_type": risk.risk_type,
        "severity": risk.severity,
        "snapshot_id": risk.snapshot_id,
        "status": risk.status,
        "supporting_evidence_ids": list(risk.supporting_evidence_ids),
        "title": risk.title,
    }


def _risk_from_payload(payload: Mapping[str, Any]) -> RiskSnapshot:
    return RiskSnapshot(
        snapshot_id=str(payload["snapshot_id"]),
        title=str(payload["title"]),
        risk_type=str(payload["risk_type"]),
        severity=str(payload["severity"]),
        status=str(payload["status"]),
        supporting_evidence_ids=tuple(
            str(item) for item in payload["supporting_evidence_ids"]
        ),
    )


def _gap_payload(gap: EvidenceGap) -> dict[str, Any]:
    return {
        "blocking": gap.blocking,
        "code": gap.code,
        "explanation": gap.explanation,
        "reason_code": gap.reason_code,
        "requirement_id": gap.requirement_id,
        "source_class": gap.source_class,
    }


def _gap_from_payload(payload: Mapping[str, Any]) -> EvidenceGap:
    return EvidenceGap(
        code=str(payload["code"]),
        source_class=str(payload["source_class"]),
        blocking=bool(payload["blocking"]),
        explanation=str(payload["explanation"]),
        requirement_id=_optional_text(payload["requirement_id"]),
        reason_code=_optional_text(payload["reason_code"]),
    )


def _eligibility_payload(eligibility: EligibilityResult) -> dict[str, Any]:
    return {
        "checks": [
            {
                "evaluated_at": check.evaluated_at.isoformat(),
                "evidence_reference": check.evidence_reference,
                "explanation": check.explanation,
                "passed": check.passed,
                "reason_code": check.reason_code,
                "rule_id": check.rule_id,
                "rule_version": check.rule_version,
            }
            for check in eligibility.checks
        ],
        "eligible": eligibility.eligible,
        "evaluated_at": eligibility.evaluated_at.isoformat(),
        "policy_version": eligibility.policy_version,
    }


def _eligibility_from_payload(payload: Mapping[str, Any]) -> EligibilityResult:
    return EligibilityResult(
        policy_version=str(payload["policy_version"]),
        eligible=bool(payload["eligible"]),
        checks=tuple(
            EligibilityCheck(
                rule_id=str(check["rule_id"]),
                rule_version=str(check["rule_version"]),
                passed=bool(check["passed"]),
                evidence_reference=_optional_text(check["evidence_reference"]),
                reason_code=str(check["reason_code"]),
                explanation=str(check["explanation"]),
                evaluated_at=_timestamp(
                    check["evaluated_at"],
                    "eligibility check timestamp",
                ),
            )
            for check in payload["checks"]
        ),
        evaluated_at=_timestamp(payload["evaluated_at"], "eligibility timestamp"),
    )


def _bundle_payload(bundle: EvidenceBundle) -> dict[str, Any]:
    return {
        "as_of_cutoff": bundle.as_of_cutoff.isoformat(),
        "catalysts": [_catalyst_payload(item) for item in bundle.catalysts],
        "content_hash": bundle.content_hash,
        "created_at": bundle.created_at.isoformat(),
        "eligibility": _eligibility_payload(bundle.eligibility),
        "evidence_policy_version": bundle.evidence_policy_version,
        "freshness_policy_version": bundle.freshness_policy_version,
        "gaps": [_gap_payload(item) for item in bundle.gaps],
        "grader_ready": bundle.grader_ready,
        "id": bundle.id,
        "manifest": [_item_payload(item) for item in bundle.manifest],
        "metrics": [_metric_payload(item) for item in bundle.metrics],
        "operator_id": bundle.operator_id,
        "research_run_id": bundle.research_run_id,
        "risks": [_risk_payload(item) for item in bundle.risks],
        "security_id": bundle.security_id,
        "security_identity": {
            "cik": bundle.security_identity.cik,
            "id": bundle.security_identity.id,
            "issuer_name": bundle.security_identity.issuer_name,
            "primary_listing_exchange": (
                bundle.security_identity.primary_listing_exchange
            ),
            "symbol": bundle.security_identity.symbol,
        },
    }


def _bundle_from_payload(payload: Mapping[str, Any]) -> EvidenceBundle:
    try:
        identity = payload["security_identity"]
        return EvidenceBundle(
            id=str(payload["id"]),
            operator_id=str(payload["operator_id"]),
            research_run_id=str(payload["research_run_id"]),
            security_id=str(payload["security_id"]),
            security_identity=SecurityIdentity(
                id=str(identity["id"]),
                cik=str(identity["cik"]),
                issuer_name=str(identity["issuer_name"]),
                symbol=str(identity["symbol"]),
                primary_listing_exchange=str(identity["primary_listing_exchange"]),
            ),
            as_of_cutoff=_timestamp(payload["as_of_cutoff"], "as-of cutoff"),
            content_hash=str(payload["content_hash"]),
            manifest=tuple(
                _item_from_payload(item) for item in payload["manifest"]
            ),
            metrics=tuple(
                _metric_from_payload(item) for item in payload["metrics"]
            ),
            catalysts=tuple(
                _catalyst_from_payload(item) for item in payload["catalysts"]
            ),
            risks=tuple(_risk_from_payload(item) for item in payload["risks"]),
            grader_ready=bool(payload["grader_ready"]),
            gaps=tuple(_gap_from_payload(item) for item in payload["gaps"]),
            eligibility=_eligibility_from_payload(payload["eligibility"]),
            evidence_policy_version=str(payload["evidence_policy_version"]),
            freshness_policy_version=str(payload["freshness_policy_version"]),
            created_at=_timestamp(payload["created_at"], "created at"),
        )
    except (KeyError, TypeError) as error:
        raise LocalEvidenceBundleStorageError(
            "evidence bundle record is invalid"
        ) from error


def _content_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class FileEvidenceBundleRepository:
    """Private restart-safe local storage for immutable Evidence Bundles."""

    def __init__(self, root: Path) -> None:
        root = Path(root)
        if root.is_symlink():
            raise LocalEvidenceBundleStorageError(
                "evidence bundle storage root must not be a symlink"
            )
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        self._root = root

    def save(self, bundle: EvidenceBundle) -> EvidenceBundle:
        existing = self.get(bundle.operator_id, bundle.id)
        if existing is not None:
            if existing != bundle:
                raise EvidenceBundleError("conflicting immutable evidence bundle")
            self._write_run_index(bundle)
            return existing
        # The run index is written first. A bundle whose index is already
        # claimed by a different bundle must be refused before any bundle
        # record exists, so a rejected save leaves nothing behind.
        self._write_run_index(bundle)
        self._write(
            self._bundle_path(bundle.operator_id, bundle.id),
            self._record(_bundle_payload(bundle), RECORD_CONTRACT_VERSION),
        )
        stored = self.get(bundle.operator_id, bundle.id)
        if stored is None or stored != bundle:
            raise LocalEvidenceBundleStorageError(
                "evidence bundle record is invalid"
            )
        return stored

    def get(self, operator_id: str, bundle_id: str) -> EvidenceBundle | None:
        path = self._bundle_path(operator_id, bundle_id)
        record = self._read(path, RECORD_CONTRACT_VERSION, "evidence_bundle")
        if record is None:
            return None
        bundle = _bundle_from_payload(record)
        if bundle.operator_id != _canonical_uuid(
            operator_id, "operator identity"
        ) or bundle.id != _canonical_uuid(bundle_id, "evidence bundle identity"):
            raise LocalEvidenceBundleStorageError(
                "evidence bundle record is invalid"
            )
        return bundle

    def get_for_run(
        self,
        operator_id: str,
        research_run_id: str,
    ) -> EvidenceBundle | None:
        bundle_id = self._run_index(operator_id, research_run_id)
        if bundle_id is None:
            return None
        bundle = self.get(operator_id, bundle_id)
        if bundle is None:
            return None
        if bundle.research_run_id != _canonical_uuid(
            research_run_id, "research run identity"
        ):
            raise LocalEvidenceBundleStorageError(
                "evidence bundle run index is invalid"
            )
        return bundle

    def _run_index(self, operator_id: str, research_run_id: str) -> str | None:
        record = self._read(
            self._run_index_path(operator_id, research_run_id),
            RUN_INDEX_CONTRACT_VERSION,
            "evidence_bundle_run_index",
        )
        if record is None:
            return None
        try:
            return _canonical_uuid(
                record["evidence_bundle_id"],
                "evidence bundle identity",
            )
        except (KeyError, TypeError) as error:
            raise LocalEvidenceBundleStorageError(
                "evidence bundle run index is invalid"
            ) from error

    def _write_run_index(self, bundle: EvidenceBundle) -> None:
        claimed = self._run_index(bundle.operator_id, bundle.research_run_id)
        if claimed is not None:
            if claimed != _canonical_uuid(bundle.id, "evidence bundle identity"):
                raise EvidenceBundleError(
                    "research run already has immutable evidence bundle"
                )
            return
        self._write(
            self._run_index_path(bundle.operator_id, bundle.research_run_id),
            self._record(
                {
                    "evidence_bundle_id": bundle.id,
                    "operator_id": bundle.operator_id,
                    "research_run_id": bundle.research_run_id,
                },
                RUN_INDEX_CONTRACT_VERSION,
            ),
        )

    @staticmethod
    def _record(payload: Mapping[str, Any], contract_version: str) -> dict[str, Any]:
        key = (
            "evidence_bundle"
            if contract_version == RECORD_CONTRACT_VERSION
            else "evidence_bundle_run_index"
        )
        return {
            "contract_version": contract_version,
            "content_sha256": _content_hash(payload),
            key: payload,
        }

    def _write(self, path: Path, record: Mapping[str, Any]) -> None:
        if path.parent.is_symlink():
            raise LocalEvidenceBundleStorageError(
                "evidence bundle directory must not be a symlink"
            )
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        body = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(body)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.chmod(temporary_path, 0o600)
        try:
            # `link` refuses to replace an existing record, so an immutable
            # record can never be silently overwritten by a concurrent write.
            os.link(temporary_path, path)
        except FileExistsError:
            pass
        finally:
            temporary_path.unlink(missing_ok=True)

    def _read(
        self,
        path: Path,
        contract_version: str,
        key: str,
    ) -> Mapping[str, Any] | None:
        if path.parent.is_symlink() or path.is_symlink() or not path.is_file():
            return None
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise LocalEvidenceBundleStorageError(
                "evidence bundle record is unreadable"
            ) from error
        if (
            not isinstance(record, dict)
            or record.get("contract_version") != contract_version
            or not isinstance(record.get(key), dict)
        ):
            raise LocalEvidenceBundleStorageError(
                "evidence bundle record is invalid"
            )
        payload = record[key]
        if record.get("content_sha256") != _content_hash(payload):
            raise LocalEvidenceBundleStorageError(
                "evidence bundle record is invalid"
            )
        return payload

    def _operator_root(self, operator_id: str) -> Path:
        return self._root / _canonical_uuid(operator_id, "operator identity")

    def _bundle_path(self, operator_id: str, bundle_id: str) -> Path:
        identity = _canonical_uuid(bundle_id, "evidence bundle identity")
        return self._operator_root(operator_id) / "bundles" / f"{identity}.json"

    def _run_index_path(self, operator_id: str, research_run_id: str) -> Path:
        identity = _canonical_uuid(research_run_id, "research run identity")
        return self._operator_root(operator_id) / "runs" / f"{identity}.json"


__all__ = [
    "FileEvidenceBundleRepository",
    "LocalEvidenceBundleStorageError",
    "RECORD_CONTRACT_VERSION",
    "RUN_INDEX_CONTRACT_VERSION",
]
