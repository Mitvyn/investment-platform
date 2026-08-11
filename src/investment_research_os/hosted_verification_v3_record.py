from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re

from investment_research_os.hosted_verification import HostedVerificationAuthorization
from investment_research_os.hosted_verification_v3 import (
    HostedVerificationExecutionAuthorization,
    HostedVerificationExecutionContract,
)


_HASH = re.compile(r"[0-9a-f]{64}")
_PROVENANCE = frozenset({"hosted_transport", "offline_fixture"})
_MUTATING_OPERATIONS = frozenset(
    {
        "attempt_duplicate_insert",
        "attempt_invalid_insert",
        "attempt_update",
    }
)


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def _authorization_matches_contract(
    authorization: HostedVerificationExecutionAuthorization,
    contract: HostedVerificationExecutionContract,
) -> bool:
    return (
        authorization.execution_contract_sha256 == contract.content_sha256
        and authorization.plan_sha256 == contract.plan_sha256
        and authorization.migration_manifest_sha256
        == contract.migration_manifest_sha256
        and authorization.plan_target_manifest_sha256
        == contract.plan_target_manifest_sha256
        and authorization.target_manifest_sha256
        == contract.execution_target_manifest_sha256
        and authorization.dispatch_registry_sha256 == contract.dispatch_registry_sha256
        and authorization.fixture_set_sha256 == contract.fixture_set_sha256
        and authorization.inventory_sha256 == contract.inventory_sha256
        and authorization.constraint_index_sha256 == contract.constraint_index_sha256
    )


@dataclass(frozen=True, slots=True)
class HostedProbeOutcome:
    probe_id: str
    passed: bool
    result_code: str
    count: int
    observed_constraint: str | None
    rollback_verified: bool
    artifact_sha256: str | None
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        probe_id: str,
        passed: bool,
        result_code: str,
        count: int,
        observed_constraint: str | None,
        rollback_verified: bool,
        artifact_sha256: str | None,
    ) -> HostedProbeOutcome:
        if (
            re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+", probe_id) is None
            or re.fullmatch(r"[a-z][a-z0-9_]*", result_code) is None
            or isinstance(count, bool)
            or count < 0
            or (observed_constraint is not None and not observed_constraint)
            or (
                artifact_sha256 is not None and _HASH.fullmatch(artifact_sha256) is None
            )
        ):
            raise ValueError("hosted verification v3 probe outcome is invalid")
        content = {
            "probe_id": probe_id,
            "passed": passed,
            "result_code": result_code,
            "count": count,
            "observed_constraint": observed_constraint,
            "rollback_verified": rollback_verified,
            "artifact_sha256": artifact_sha256,
        }
        return cls(**content, content_sha256=_sha256(content))

    def has_valid_content_hash(self) -> bool:
        return self.content_sha256 == _sha256(
            {
                "probe_id": self.probe_id,
                "passed": self.passed,
                "result_code": self.result_code,
                "count": self.count,
                "observed_constraint": self.observed_constraint,
                "rollback_verified": self.rollback_verified,
                "artifact_sha256": self.artifact_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class HostedVerificationExecutionReport:
    report_version: str
    execution_contract_sha256: str
    execution_authorization_sha256: str
    passed: bool
    blocking_reason_codes: tuple[str, ...]
    probe_outcomes: tuple[HostedProbeOutcome, ...]
    residue_suspected: tuple[str, ...]
    checked_at: datetime
    execution_provenance: str
    abort_remaining_mutations: bool
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        execution_contract: HostedVerificationExecutionContract,
        execution_authorization: HostedVerificationExecutionAuthorization,
        claimed_passed: bool,
        blocking_reason_codes: tuple[str, ...],
        probe_outcomes: tuple[HostedProbeOutcome, ...],
        residue_suspected: tuple[str, ...],
        checked_at: datetime,
        execution_provenance: str,
    ) -> HostedVerificationExecutionReport:
        if not execution_contract.has_valid_content_hash():
            raise ValueError("hosted verification v3 report contract is invalid")
        if not execution_authorization.has_valid_content_hash():
            raise ValueError("hosted verification v3 report authorization is invalid")
        if not _authorization_matches_contract(
            execution_authorization,
            execution_contract,
        ):
            raise ValueError("hosted verification v3 report binding is invalid")
        if checked_at.tzinfo is None:
            raise ValueError("hosted verification v3 report time is invalid")
        if execution_provenance not in _PROVENANCE:
            raise ValueError("hosted verification v3 report provenance is invalid")
        ordered_outcomes = tuple(sorted(probe_outcomes, key=lambda item: item.probe_id))
        if len({item.probe_id for item in ordered_outcomes}) != len(
            ordered_outcomes
        ) or any(not item.has_valid_content_hash() for item in ordered_outcomes):
            raise ValueError("hosted verification v3 report outcomes are invalid")
        dispatches = {item.probe_id: item for item in execution_contract.dispatches}
        if any(item.probe_id not in dispatches for item in ordered_outcomes):
            raise ValueError("hosted verification v3 report outcome is unplanned")

        reasons = set(blocking_reason_codes)
        if any(
            re.fullmatch(r"[a-z][a-z0-9_.:-]*", reason) is None for reason in reasons
        ):
            raise ValueError("hosted verification v3 report reason is invalid")
        outcomes_by_id = {item.probe_id: item for item in ordered_outcomes}
        for probe_id in dispatches:
            if probe_id not in outcomes_by_id:
                reasons.add(f"probe_missing:{probe_id}")
        ordered_residue = tuple(sorted(set(residue_suspected)))
        if any(
            re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+", residue) is None
            for residue in ordered_residue
        ):
            raise ValueError("hosted verification v3 residue identity is invalid")
        reasons.update(f"residue_suspected:{residue}" for residue in ordered_residue)
        abort_remaining_mutations = bool(ordered_residue)
        for outcome in ordered_outcomes:
            dispatch = dispatches[outcome.probe_id]
            if not outcome.passed:
                reasons.add(f"probe_failed:{outcome.probe_id}")
            if (
                dispatch.expected_constraint is not None
                and outcome.observed_constraint != dispatch.expected_constraint
            ):
                reasons.add(f"constraint_mismatch:{outcome.probe_id}")
            if (
                dispatch.operation in _MUTATING_OPERATIONS
                and not outcome.rollback_verified
            ):
                reasons.add(f"rollback_unproven:{dispatch.fixture_id}")
                abort_remaining_mutations = True
        ordered_reasons = tuple(sorted(reasons))
        passed = not ordered_reasons and len(ordered_outcomes) == len(dispatches)
        if claimed_passed != passed:
            raise ValueError("hosted verification v3 claimed outcome is inconsistent")
        if passed and execution_provenance != "hosted_transport":
            raise ValueError(
                "hosted verification v3 passing report is not hosted evidence"
            )
        version = "hosted-verification-execution-report.v3"
        content = {
            "report_version": version,
            "execution_contract_sha256": execution_contract.content_sha256,
            "execution_authorization_sha256": execution_authorization.content_sha256,
            "passed": passed,
            "blocking_reason_codes": list(ordered_reasons),
            "probe_outcomes": [item.content_sha256 for item in ordered_outcomes],
            "residue_suspected": list(ordered_residue),
            "checked_at": checked_at.isoformat(),
            "execution_provenance": execution_provenance,
            "abort_remaining_mutations": abort_remaining_mutations,
        }
        return cls(
            report_version=version,
            execution_contract_sha256=execution_contract.content_sha256,
            execution_authorization_sha256=execution_authorization.content_sha256,
            passed=passed,
            blocking_reason_codes=ordered_reasons,
            probe_outcomes=ordered_outcomes,
            residue_suspected=ordered_residue,
            checked_at=checked_at,
            execution_provenance=execution_provenance,
            abort_remaining_mutations=abort_remaining_mutations,
            content_sha256=_sha256(content),
        )

    def has_valid_content_hash(self) -> bool:
        return all(
            outcome.has_valid_content_hash() for outcome in self.probe_outcomes
        ) and self.content_sha256 == _sha256(
            {
                "report_version": self.report_version,
                "execution_contract_sha256": self.execution_contract_sha256,
                "execution_authorization_sha256": self.execution_authorization_sha256,
                "passed": self.passed,
                "blocking_reason_codes": list(self.blocking_reason_codes),
                "probe_outcomes": [item.content_sha256 for item in self.probe_outcomes],
                "residue_suspected": list(self.residue_suspected),
                "checked_at": self.checked_at.isoformat(),
                "execution_provenance": self.execution_provenance,
                "abort_remaining_mutations": self.abort_remaining_mutations,
            }
        )


@dataclass(frozen=True, slots=True)
class HostedVerificationExecutionRecord:
    record_version: str
    issue_id: str
    database_scope: str
    plan_sha256: str
    migration_manifest_sha256: str
    plan_target_manifest_sha256: str
    execution_target_manifest_sha256: str
    dispatch_registry_sha256: str
    fixture_set_sha256: str
    inventory_sha256: str
    constraint_index_sha256: str
    execution_contract_sha256: str
    execution_authorization_sha256: str
    report_sha256: str
    execution_provenance: str
    checked_at: datetime
    passed: bool
    blocking_reason_codes: tuple[str, ...]
    probe_outcomes: tuple[HostedProbeOutcome, ...]
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        execution_contract: HostedVerificationExecutionContract,
        authorization: HostedVerificationAuthorization,
        execution_authorization: HostedVerificationExecutionAuthorization,
        report: HostedVerificationExecutionReport,
        inventory_sha256: str,
        constraint_index_sha256: str,
    ) -> HostedVerificationExecutionRecord:
        authorization.assert_valid_contract()
        if (
            not authorization.has_valid_content_hash()
            or not execution_contract.has_valid_content_hash()
            or not execution_authorization.has_valid_content_hash()
            or not report.has_valid_content_hash()
        ):
            raise ValueError("hosted verification v3 record input is invalid")
        if (
            execution_authorization.authorization_sha256 != authorization.content_sha256
            or report.execution_contract_sha256 != execution_contract.content_sha256
            or report.execution_authorization_sha256
            != execution_authorization.content_sha256
        ):
            raise ValueError("hosted verification v3 record binding is invalid")
        if not (
            authorization.issued_at <= report.checked_at < authorization.expires_at
        ):
            raise ValueError("hosted verification v3 record time is unauthorized")
        if (
            _HASH.fullmatch(inventory_sha256) is None
            or _HASH.fullmatch(constraint_index_sha256) is None
            or inventory_sha256 != execution_contract.inventory_sha256
            or constraint_index_sha256 != execution_contract.constraint_index_sha256
        ):
            raise ValueError("hosted verification v3 record schema hash is invalid")
        version = "hosted-verification-execution-record.v3"
        content = {
            "record_version": version,
            "issue_id": authorization.issue_id,
            "database_scope": authorization.database_scope,
            "plan_sha256": execution_contract.plan_sha256,
            "migration_manifest_sha256": execution_contract.migration_manifest_sha256,
            "plan_target_manifest_sha256": (
                execution_contract.plan_target_manifest_sha256
            ),
            "execution_target_manifest_sha256": (
                execution_contract.execution_target_manifest_sha256
            ),
            "dispatch_registry_sha256": execution_contract.dispatch_registry_sha256,
            "fixture_set_sha256": execution_contract.fixture_set_sha256,
            "inventory_sha256": inventory_sha256,
            "constraint_index_sha256": constraint_index_sha256,
            "execution_contract_sha256": execution_contract.content_sha256,
            "execution_authorization_sha256": execution_authorization.content_sha256,
            "report_sha256": report.content_sha256,
            "execution_provenance": report.execution_provenance,
            "checked_at": report.checked_at.isoformat(),
            "passed": report.passed,
            "blocking_reason_codes": list(report.blocking_reason_codes),
            "probe_outcomes": [item.content_sha256 for item in report.probe_outcomes],
        }
        return cls(
            record_version=version,
            issue_id=authorization.issue_id,
            database_scope=authorization.database_scope,
            plan_sha256=execution_contract.plan_sha256,
            migration_manifest_sha256=execution_contract.migration_manifest_sha256,
            plan_target_manifest_sha256=execution_contract.plan_target_manifest_sha256,
            execution_target_manifest_sha256=(
                execution_contract.execution_target_manifest_sha256
            ),
            dispatch_registry_sha256=execution_contract.dispatch_registry_sha256,
            fixture_set_sha256=execution_contract.fixture_set_sha256,
            inventory_sha256=inventory_sha256,
            constraint_index_sha256=constraint_index_sha256,
            execution_contract_sha256=execution_contract.content_sha256,
            execution_authorization_sha256=execution_authorization.content_sha256,
            report_sha256=report.content_sha256,
            execution_provenance=report.execution_provenance,
            checked_at=report.checked_at,
            passed=report.passed,
            blocking_reason_codes=report.blocking_reason_codes,
            probe_outcomes=report.probe_outcomes,
            content_sha256=_sha256(content),
        )

    def has_valid_content_hash(self) -> bool:
        return all(
            outcome.has_valid_content_hash() for outcome in self.probe_outcomes
        ) and self.content_sha256 == _sha256(
            {
                "record_version": self.record_version,
                "issue_id": self.issue_id,
                "database_scope": self.database_scope,
                "plan_sha256": self.plan_sha256,
                "migration_manifest_sha256": self.migration_manifest_sha256,
                "plan_target_manifest_sha256": self.plan_target_manifest_sha256,
                "execution_target_manifest_sha256": (
                    self.execution_target_manifest_sha256
                ),
                "dispatch_registry_sha256": self.dispatch_registry_sha256,
                "fixture_set_sha256": self.fixture_set_sha256,
                "inventory_sha256": self.inventory_sha256,
                "constraint_index_sha256": self.constraint_index_sha256,
                "execution_contract_sha256": self.execution_contract_sha256,
                "execution_authorization_sha256": (self.execution_authorization_sha256),
                "report_sha256": self.report_sha256,
                "execution_provenance": self.execution_provenance,
                "checked_at": self.checked_at.isoformat(),
                "passed": self.passed,
                "blocking_reason_codes": list(self.blocking_reason_codes),
                "probe_outcomes": [item.content_sha256 for item in self.probe_outcomes],
            }
        )


__all__ = [
    "HostedProbeOutcome",
    "HostedVerificationExecutionRecord",
    "HostedVerificationExecutionReport",
]
