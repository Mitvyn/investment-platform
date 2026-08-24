"""Desktop-local durable persistence for the Research Run repository port.

`InMemoryResearchRunRepository` cannot survive a worker restart and the
Supabase repository requires hosted access. This adapter satisfies the same
`ResearchRunRepository` protocol using owner-scoped immutable local files so a
locally executed command keeps exactly one Research Run across restarts.

Records carry no secrets, provider payloads, or archive paths.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping

from . import (
    EligibilityCheck,
    EligibilityResult,
    ResearchRun,
    SecurityIdentity,
)


RECORD_CONTRACT_VERSION = "local_research_run_record.v1"


class LocalResearchRunStorageError(ValueError):
    """Raised when durable local Research Run state violates its contract."""


def _canonical_uuid(value: object, label: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as error:
        raise LocalResearchRunStorageError(f"{label} must be a UUID") from error


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise LocalResearchRunStorageError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise LocalResearchRunStorageError(f"{label} is invalid") from error
    if parsed.tzinfo is None:
        raise LocalResearchRunStorageError(f"{label} must be timezone aware")
    return parsed.astimezone(UTC)


def _run_payload(run: ResearchRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "operator_id": run.operator_id,
        "security_id": run.security_id,
        "security_identity": {
            "id": run.security_identity.id,
            "cik": run.security_identity.cik,
            "issuer_name": run.security_identity.issuer_name,
            "symbol": run.security_identity.symbol,
            "primary_listing_exchange": (
                run.security_identity.primary_listing_exchange
            ),
        },
        "question_type": run.question_type,
        "question_type_version": run.question_type_version,
        "workflow_config_version": run.workflow_config_version,
        "thesis_contract_id": run.thesis_contract_id,
        "as_of_cutoff": run.as_of_cutoff.isoformat(),
        "operator_focus_original": run.operator_focus_original,
        "operator_focus_normalized": run.operator_focus_normalized,
        "status": run.status,
        "idempotency_key": run.idempotency_key,
        "eligibility": {
            "policy_version": run.eligibility.policy_version,
            "eligible": run.eligibility.eligible,
            "evaluated_at": run.eligibility.evaluated_at.isoformat(),
            "checks": [
                {
                    "rule_id": check.rule_id,
                    "rule_version": check.rule_version,
                    "passed": check.passed,
                    "evidence_reference": check.evidence_reference,
                    "reason_code": check.reason_code,
                    "explanation": check.explanation,
                    "evaluated_at": check.evaluated_at.isoformat(),
                }
                for check in run.eligibility.checks
            ],
        },
        "created_at": run.created_at.isoformat(),
    }


def _run_from_payload(payload: Mapping[str, Any]) -> ResearchRun:
    try:
        identity = payload["security_identity"]
        eligibility = payload["eligibility"]
        return ResearchRun(
            id=str(payload["id"]),
            operator_id=str(payload["operator_id"]),
            security_id=str(payload["security_id"]),
            security_identity=SecurityIdentity(
                id=str(identity["id"]),
                cik=str(identity["cik"]),
                issuer_name=str(identity["issuer_name"]),
                symbol=str(identity["symbol"]),
                primary_listing_exchange=str(identity["primary_listing_exchange"]),
            ),
            question_type=str(payload["question_type"]),
            question_type_version=str(payload["question_type_version"]),
            workflow_config_version=str(payload["workflow_config_version"]),
            thesis_contract_id=str(payload["thesis_contract_id"]),
            as_of_cutoff=_timestamp(payload["as_of_cutoff"], "as-of cutoff"),
            operator_focus_original=(
                None
                if payload["operator_focus_original"] is None
                else str(payload["operator_focus_original"])
            ),
            operator_focus_normalized=(
                None
                if payload["operator_focus_normalized"] is None
                else str(payload["operator_focus_normalized"])
            ),
            status=str(payload["status"]),
            idempotency_key=str(payload["idempotency_key"]),
            eligibility=EligibilityResult(
                policy_version=str(eligibility["policy_version"]),
                eligible=bool(eligibility["eligible"]),
                checks=tuple(
                    EligibilityCheck(
                        rule_id=str(check["rule_id"]),
                        rule_version=str(check["rule_version"]),
                        passed=bool(check["passed"]),
                        evidence_reference=(
                            None
                            if check["evidence_reference"] is None
                            else str(check["evidence_reference"])
                        ),
                        reason_code=str(check["reason_code"]),
                        explanation=str(check["explanation"]),
                        evaluated_at=_timestamp(
                            check["evaluated_at"],
                            "eligibility check timestamp",
                        ),
                    )
                    for check in eligibility["checks"]
                ),
                evaluated_at=_timestamp(
                    eligibility["evaluated_at"],
                    "eligibility timestamp",
                ),
            ),
            created_at=_timestamp(payload["created_at"], "created at"),
        )
    except (KeyError, TypeError) as error:
        raise LocalResearchRunStorageError("research run record is invalid") from error


def _content_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class FileResearchRunRepository:
    """Private restart-safe local storage for immutable Research Runs."""

    def __init__(self, root: Path) -> None:
        root = Path(root)
        if root.is_symlink():
            raise LocalResearchRunStorageError(
                "research run storage root must not be a symlink"
            )
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        self._root = root

    def save(self, run: ResearchRun) -> ResearchRun:
        existing = self.get(run.operator_id, run.id)
        if existing is not None:
            return existing
        payload = _run_payload(run)
        record = {
            "contract_version": RECORD_CONTRACT_VERSION,
            "content_sha256": _content_hash(payload),
            "research_run": payload,
        }
        path = self._run_path(run.operator_id, run.id)
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
            os.link(temporary_path, path)
        except FileExistsError:
            temporary_path.unlink(missing_ok=True)
            stored = self.get(run.operator_id, run.id)
            if stored is None:
                raise LocalResearchRunStorageError(
                    "research run record is invalid"
                ) from None
            return stored
        finally:
            temporary_path.unlink(missing_ok=True)
        return run

    def get(self, operator_id: str, run_id: str) -> ResearchRun | None:
        path = self._run_path(operator_id, run_id)
        if path.is_symlink() or not path.is_file():
            return None
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise LocalResearchRunStorageError(
                "research run record is unreadable"
            ) from error
        if (
            not isinstance(record, dict)
            or record.get("contract_version") != RECORD_CONTRACT_VERSION
            or not isinstance(record.get("research_run"), dict)
        ):
            raise LocalResearchRunStorageError("research run record is invalid")
        payload = record["research_run"]
        if record.get("content_sha256") != _content_hash(payload):
            raise LocalResearchRunStorageError("research run record is invalid")
        run = _run_from_payload(payload)
        if run.operator_id != _canonical_uuid(
            operator_id, "operator identity"
        ) or run.id != _canonical_uuid(run_id, "research run identity"):
            raise LocalResearchRunStorageError("research run record is invalid")
        return run

    def _run_path(self, operator_id: str, run_id: str) -> Path:
        return (
            self._root
            / _canonical_uuid(operator_id, "operator identity")
            / f"{_canonical_uuid(run_id, 'research run identity')}.json"
        )


__all__ = [
    "FileResearchRunRepository",
    "LocalResearchRunStorageError",
    "RECORD_CONTRACT_VERSION",
]
