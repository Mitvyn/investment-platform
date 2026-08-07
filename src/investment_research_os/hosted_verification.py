from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from typing import Protocol

from investment_research_os.migration_audit import audit_iros_migration_batch


HOSTED_VERIFICATION_SCOPES = (
    "linked_migration_history_read",
    "owner_isolation_read",
    "raw_provider_audit_probe",
    "negative_constraint_probe",
    "valuation_gate_probe",
    "database_advisor_read",
)
HOSTED_VERIFICATION_CATEGORIES = (
    "migration_history",
    "owner_isolation",
    "raw_provider_audit",
    "immutable_constraint",
    "duplicate_prevention",
    "valuation_gate",
    "database_advisor",
)
IROS_HOSTED_VERIFICATION_TARGETS = (
    "iros_jobs",
    "iros_read_raw_provider_payload",
    "iros_research_run_commands",
    "iros_securities",
    "iros_v_current_operator_decisions",
    "iros_v_latest_holdings",
    "iros_v_market_series",
    "iros_v_model_cost_attempts",
    "iros_v_model_cost_budgets",
    "iros_v_model_cost_reservations",
    "iros_v_operator_decision_effects",
    "iros_v_operator_decision_history",
    "iros_v_research_run_command_progress",
    "iros_v_research_run_committee_memos",
    "iros_v_research_run_committees",
    "iros_v_research_run_eligibility",
    "iros_v_research_run_evidence_bundle",
    "iros_v_research_run_grader_executions",
    "iros_v_research_run_readiness",
    "iros_v_research_run_thesis",
    "iros_v_research_run_valuation_snapshot",
    "iros_v_security_catalyst_context",
    "iros_v_security_claim_evidence_trace",
    "iros_v_security_financial_health",
    "iros_v_security_market_context",
    "iros_v_security_risk_context",
    "iros_v_thesis_chains",
    "iros_watchlist_items",
)
_PROBE_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+")
_MAX_AUTHORIZATION_LIFETIME = timedelta(minutes=30)


def _content_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class HostedMigrationManifestEntry:
    filename: str
    content_sha256: str

    def __post_init__(self) -> None:
        if not self.filename.strip() or not re.fullmatch(
            r"[0-9]{14}_iros_[a-z0-9_]+\.sql",
            self.filename,
        ):
            raise ValueError("hosted verification migration filename is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", self.content_sha256):
            raise ValueError("hosted verification migration hash is invalid")


@dataclass(frozen=True, slots=True)
class HostedVerificationAuthorization:
    authorization_id: str
    issue_id: str
    database_scope: str
    operator_id: str
    owner_subject_id: str
    unrelated_subject_id: str
    audit_subject_id: str
    turn_id: str
    issued_at: datetime
    expires_at: datetime
    authorized_scopes: tuple[str, ...]
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        authorization_id: str,
        issue_id: str,
        database_scope: str,
        operator_id: str,
        owner_subject_id: str,
        unrelated_subject_id: str,
        audit_subject_id: str,
        turn_id: str,
        issued_at: datetime,
        expires_at: datetime,
        authorized_scopes: tuple[str, ...],
    ) -> HostedVerificationAuthorization:
        identifiers = (
            authorization_id,
            operator_id,
            owner_subject_id,
            unrelated_subject_id,
            audit_subject_id,
            turn_id,
        )
        if any(
            not isinstance(value, str) or not value.strip() for value in identifiers
        ):
            raise ValueError("hosted verification authorization identity is invalid")
        if issue_id != "IRO-052":
            raise ValueError("hosted verification issue is invalid")
        if database_scope != "iros_only":
            raise ValueError("hosted verification database scope is invalid")
        if issued_at.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("hosted verification authorization time is invalid")
        if expires_at <= issued_at:
            raise ValueError("hosted verification authorization expiry is invalid")
        if expires_at - issued_at > _MAX_AUTHORIZATION_LIFETIME:
            raise ValueError("hosted verification authorization lifetime is invalid")
        if len({owner_subject_id, unrelated_subject_id, audit_subject_id}) != 3:
            raise ValueError("hosted verification subjects must be distinct")
        if authorized_scopes != HOSTED_VERIFICATION_SCOPES:
            raise ValueError("hosted verification authorization scopes are invalid")
        content = cls._content(
            authorization_id=authorization_id,
            issue_id=issue_id,
            database_scope=database_scope,
            operator_id=operator_id,
            owner_subject_id=owner_subject_id,
            unrelated_subject_id=unrelated_subject_id,
            audit_subject_id=audit_subject_id,
            turn_id=turn_id,
            issued_at=issued_at,
            expires_at=expires_at,
            authorized_scopes=authorized_scopes,
        )
        return cls(
            authorization_id=authorization_id,
            issue_id=issue_id,
            database_scope=database_scope,
            operator_id=operator_id,
            owner_subject_id=owner_subject_id,
            unrelated_subject_id=unrelated_subject_id,
            audit_subject_id=audit_subject_id,
            turn_id=turn_id,
            issued_at=issued_at,
            expires_at=expires_at,
            authorized_scopes=authorized_scopes,
            content_sha256=_content_sha256(content),
        )

    @staticmethod
    def _content(
        *,
        authorization_id: str,
        issue_id: str,
        database_scope: str,
        operator_id: str,
        owner_subject_id: str,
        unrelated_subject_id: str,
        audit_subject_id: str,
        turn_id: str,
        issued_at: datetime,
        expires_at: datetime,
        authorized_scopes: tuple[str, ...],
    ) -> dict[str, object]:
        return {
            "authorization_id": authorization_id,
            "issue_id": issue_id,
            "database_scope": database_scope,
            "operator_id": operator_id,
            "owner_subject_id": owner_subject_id,
            "unrelated_subject_id": unrelated_subject_id,
            "audit_subject_id": audit_subject_id,
            "turn_id": turn_id,
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "authorized_scopes": list(authorized_scopes),
        }

    def assert_valid_contract(self) -> None:
        if self.issue_id != "IRO-052":
            raise ValueError("hosted verification issue is invalid")
        if self.database_scope != "iros_only":
            raise ValueError("hosted verification database scope is invalid")
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("hosted verification authorization time is invalid")
        if self.expires_at <= self.issued_at:
            raise ValueError("hosted verification authorization expiry is invalid")
        if self.expires_at - self.issued_at > _MAX_AUTHORIZATION_LIFETIME:
            raise ValueError("hosted verification authorization lifetime is invalid")

    def has_valid_content_hash(self) -> bool:
        return self.content_sha256 == _content_sha256(
            self._content(
                authorization_id=self.authorization_id,
                issue_id=self.issue_id,
                database_scope=self.database_scope,
                operator_id=self.operator_id,
                owner_subject_id=self.owner_subject_id,
                unrelated_subject_id=self.unrelated_subject_id,
                audit_subject_id=self.audit_subject_id,
                turn_id=self.turn_id,
                issued_at=self.issued_at,
                expires_at=self.expires_at,
                authorized_scopes=self.authorized_scopes,
            )
        )


@dataclass(frozen=True, slots=True)
class HostedVerificationProbe:
    probe_id: str
    category: str
    required_scope: str
    expected_result_code: str | None = None
    expected_count: int | None = None

    def __post_init__(self) -> None:
        if not _PROBE_ID_PATTERN.fullmatch(self.probe_id):
            raise ValueError("hosted verification probe ID is invalid")
        if self.category not in HOSTED_VERIFICATION_CATEGORIES:
            raise ValueError("hosted verification probe category is invalid")
        if self.required_scope not in HOSTED_VERIFICATION_SCOPES:
            raise ValueError("hosted verification probe scope is invalid")
        if self.expected_result_code is not None and not re.fullmatch(
            r"[a-z][a-z0-9_]*",
            self.expected_result_code,
        ):
            raise ValueError("hosted verification expected result code is invalid")
        if self.expected_count is not None and (
            isinstance(self.expected_count, bool) or self.expected_count < 0
        ):
            raise ValueError("hosted verification expected count is invalid")


@dataclass(frozen=True, slots=True)
class HostedVerificationProbeResult:
    probe_id: str
    category: str
    passed: bool
    result_code: str
    count: int
    artifact_sha256: str | None = None

    @classmethod
    def passed_result(
        cls,
        *,
        probe_id: str,
        category: str,
        result_code: str,
        count: int,
        artifact_sha256: str | None = None,
    ) -> HostedVerificationProbeResult:
        return cls(
            probe_id=probe_id,
            category=category,
            passed=True,
            result_code=result_code,
            count=count,
            artifact_sha256=artifact_sha256,
        )

    @classmethod
    def failed_result(
        cls,
        *,
        probe_id: str,
        category: str,
        result_code: str,
        count: int,
        artifact_sha256: str | None = None,
    ) -> HostedVerificationProbeResult:
        return cls(
            probe_id=probe_id,
            category=category,
            passed=False,
            result_code=result_code,
            count=count,
            artifact_sha256=artifact_sha256,
        )

    def __post_init__(self) -> None:
        if not _PROBE_ID_PATTERN.fullmatch(self.probe_id):
            raise ValueError("hosted verification result identity is invalid")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.result_code):
            raise ValueError("hosted verification result code is invalid")
        if self.category not in HOSTED_VERIFICATION_CATEGORIES:
            raise ValueError("hosted verification result category is invalid")
        if isinstance(self.count, bool) or self.count < 0:
            raise ValueError("hosted verification result count is invalid")
        if self.artifact_sha256 is not None and (
            len(self.artifact_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.artifact_sha256
            )
        ):
            raise ValueError("hosted verification artifact hash is invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "probe_id": self.probe_id,
            "category": self.category,
            "passed": self.passed,
            "result_code": self.result_code,
            "count": self.count,
            "artifact_sha256": self.artifact_sha256,
        }


@dataclass(frozen=True, slots=True)
class HostedVerificationPlan:
    plan_version: str
    migration_manifest: tuple[HostedMigrationManifestEntry, ...]
    target_objects: tuple[str, ...]
    probes: tuple[HostedVerificationProbe, ...]
    content_sha256: str

    @classmethod
    def empty(cls) -> HostedVerificationPlan:
        return cls.freeze(probes=())

    @classmethod
    def freeze(
        cls,
        *,
        probes: tuple[HostedVerificationProbe, ...],
        migration_manifest: tuple[HostedMigrationManifestEntry, ...] = (),
        target_objects: tuple[str, ...] = (),
    ) -> HostedVerificationPlan:
        if len({probe.probe_id for probe in probes}) != len(probes):
            raise ValueError("hosted verification probe IDs must be unique")
        if len({entry.filename for entry in migration_manifest}) != len(
            migration_manifest
        ):
            raise ValueError("hosted verification migration filenames must be unique")
        if len(set(target_objects)) != len(target_objects):
            raise ValueError("hosted verification targets must be unique")
        if any(
            not re.fullmatch(r"iros_[a-z0-9_]+", target) for target in target_objects
        ):
            raise ValueError("hosted verification target is outside iros namespace")
        ordered_manifest = tuple(
            sorted(migration_manifest, key=lambda entry: entry.filename)
        )
        ordered_targets = tuple(sorted(target_objects))
        ordered = tuple(sorted(probes, key=lambda probe: probe.probe_id))
        plan_version = "hosted-verification-plan.v1"
        content = cls._content(
            plan_version=plan_version,
            migration_manifest=ordered_manifest,
            target_objects=ordered_targets,
            probes=ordered,
        )
        return cls(
            plan_version=plan_version,
            migration_manifest=ordered_manifest,
            target_objects=ordered_targets,
            probes=ordered,
            content_sha256=_content_sha256(content),
        )

    @staticmethod
    def _content(
        *,
        plan_version: str,
        migration_manifest: tuple[HostedMigrationManifestEntry, ...],
        target_objects: tuple[str, ...],
        probes: tuple[HostedVerificationProbe, ...],
    ) -> dict[str, object]:
        return {
            "plan_version": plan_version,
            "migration_manifest": [
                {
                    "filename": entry.filename,
                    "content_sha256": entry.content_sha256,
                }
                for entry in migration_manifest
            ],
            "target_objects": list(target_objects),
            "probes": [
                {
                    "probe_id": probe.probe_id,
                    "category": probe.category,
                    "required_scope": probe.required_scope,
                    "expected_result_code": probe.expected_result_code,
                    "expected_count": probe.expected_count,
                }
                for probe in probes
            ],
        }

    def has_valid_content_hash(self) -> bool:
        return self.content_sha256 == _content_sha256(
            self._content(
                plan_version=self.plan_version,
                migration_manifest=self.migration_manifest,
                target_objects=self.target_objects,
                probes=self.probes,
            )
        )

    @staticmethod
    def required_scopes() -> tuple[str, ...]:
        return HOSTED_VERIFICATION_SCOPES

    @property
    def migration_manifest_sha256(self) -> str:
        return _content_sha256(
            [
                {
                    "filename": entry.filename,
                    "content_sha256": entry.content_sha256,
                }
                for entry in self.migration_manifest
            ]
        )

    @property
    def target_manifest_sha256(self) -> str:
        return _content_sha256(list(self.target_objects))


def build_hosted_verification_plan(
    *,
    migration_paths: tuple[Path, ...],
    target_objects: tuple[str, ...],
    probes: tuple[HostedVerificationProbe, ...],
) -> HostedVerificationPlan:
    manifest = tuple(
        HostedMigrationManifestEntry(
            filename=path.name,
            content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in migration_paths
    )
    return HostedVerificationPlan.freeze(
        migration_manifest=manifest,
        target_objects=target_objects,
        probes=probes,
    )


def build_default_iros_hosted_verification_plan(
    *,
    migration_paths: tuple[Path, ...],
) -> HostedVerificationPlan:
    migration_audit = audit_iros_migration_batch(migration_paths)
    if not migration_audit.passed:
        raise ValueError("hosted verification migration batch failed IROS audit")
    probe_specs = (
        (
            (
                "migration.linked_history",
                "migration_history",
                "linked_migration_history_read",
                "reviewed_batch_matches",
                len(migration_paths),
            ),
            (
                "access.owner",
                "owner_isolation",
                "owner_isolation_read",
                "owner_access_verified",
                len(IROS_HOSTED_VERIFICATION_TARGETS),
            ),
            (
                "access.unrelated_denied",
                "owner_isolation",
                "owner_isolation_read",
                "unrelated_access_denied",
                len(IROS_HOSTED_VERIFICATION_TARGETS),
            ),
            (
                "access.anonymous_denied",
                "owner_isolation",
                "owner_isolation_read",
                "anonymous_access_denied",
                len(IROS_HOSTED_VERIFICATION_TARGETS),
            ),
            (
                "access.least_privilege_grants",
                "owner_isolation",
                "owner_isolation_read",
                "least_privilege_grants_verified",
                len(IROS_HOSTED_VERIFICATION_TARGETS),
            ),
            (
                "access.security_invoker_views",
                "owner_isolation",
                "owner_isolation_read",
                "security_invoker_views_verified",
                len(IROS_HOSTED_VERIFICATION_TARGETS),
            ),
            (
                "raw_audit.ordinary_denied",
                "raw_provider_audit",
                "raw_provider_audit_probe",
                "ordinary_access_denied",
                1,
            ),
            (
                "raw_audit.owner_permitted",
                "raw_provider_audit",
                "raw_provider_audit_probe",
                "owner_access_permitted",
                1,
            ),
            (
                "raw_audit.cross_owner_denied",
                "raw_provider_audit",
                "raw_provider_audit_probe",
                "cross_owner_access_denied",
                1,
            ),
            (
                "raw_audit.access_event",
                "raw_provider_audit",
                "raw_provider_audit_probe",
                "audit_event_recorded",
                1,
            ),
            (
                "advisor.iros_findings",
                "database_advisor",
                "database_advisor_read",
                "no_unaddressed_findings",
                0,
            ),
        )
        + tuple(
            (
                f"immutable.{identity}",
                "immutable_constraint",
                "negative_constraint_probe",
                "mutation_rejected",
                1,
            )
            for identity in (
                "research_run",
                "grader_execution",
                "committee",
                "memo",
                "thesis",
                "operator_decision",
                "command",
                "market_series",
            )
        )
        + tuple(
            (
                f"duplicate.{identity}",
                "duplicate_prevention",
                "negative_constraint_probe",
                "duplicate_rejected",
                1,
            )
            for identity in (
                "research_run",
                "grader_execution",
                "committee",
                "memo",
                "thesis",
                "operator_decision",
                "command",
                "market_series",
            )
        )
        + tuple(
            (
                f"valuation.{state}",
                "valuation_gate",
                "valuation_gate_probe",
                "readiness_rejected",
                1,
            )
            for state in (
                "missing",
                "invalid",
                "stale",
                "pre_material_evidence",
                "indeterminate",
            )
        )
    )
    return build_hosted_verification_plan(
        migration_paths=migration_paths,
        target_objects=IROS_HOSTED_VERIFICATION_TARGETS,
        probes=tuple(
            HostedVerificationProbe(
                probe_id=probe_id,
                category=category,
                required_scope=required_scope,
                expected_result_code=expected_result_code,
                expected_count=expected_count,
            )
            for (
                probe_id,
                category,
                required_scope,
                expected_result_code,
                expected_count,
            ) in probe_specs
        ),
    )


def build_matching_offline_probe_results(
    plan: HostedVerificationPlan,
) -> tuple[HostedVerificationProbeResult, ...]:
    """Build redacted fake results for contract tests; never proves hosted state."""
    results: list[HostedVerificationProbeResult] = []
    for probe in plan.probes:
        if probe.expected_result_code is None or probe.expected_count is None:
            raise ValueError(
                "offline hosted verification fixture requires exact probe contract"
            )
        artifact_sha256 = None
        if probe.category == "migration_history":
            artifact_sha256 = plan.migration_manifest_sha256
        elif probe.category == "owner_isolation":
            artifact_sha256 = plan.target_manifest_sha256
        results.append(
            HostedVerificationProbeResult.passed_result(
                probe_id=probe.probe_id,
                category=probe.category,
                result_code=probe.expected_result_code,
                count=probe.expected_count,
                artifact_sha256=artifact_sha256,
            )
        )
    return tuple(results)


@dataclass(frozen=True, slots=True)
class HostedVerificationReport:
    passed: bool
    blocking_reason_codes: tuple[str, ...]
    probe_results: tuple[HostedVerificationProbeResult, ...]
    checked_at: datetime
    plan_sha256: str | None = None
    authorization_sha256: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "blocking_reason_codes": list(self.blocking_reason_codes),
            "probe_results": [result.as_dict() for result in self.probe_results],
            "checked_at": self.checked_at.isoformat(),
            "plan_sha256": self.plan_sha256,
            "authorization_sha256": self.authorization_sha256,
        }


@dataclass(frozen=True, slots=True)
class HostedVerificationRecord:
    record_version: str
    issue_id: str
    database_scope: str
    plan_version: str
    plan_sha256: str
    migration_manifest_sha256: str
    target_manifest_sha256: str
    authorization_sha256: str
    operator_sha256: str
    subject_manifest_sha256: str
    checked_at: datetime
    passed: bool
    blocking_reason_codes: tuple[str, ...]
    probe_results: tuple[HostedVerificationProbeResult, ...]
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        plan: HostedVerificationPlan,
        authorization: HostedVerificationAuthorization,
        report: HostedVerificationReport,
        checked_at: datetime,
    ) -> HostedVerificationRecord:
        if checked_at.tzinfo is None:
            raise ValueError("hosted verification record time is invalid")
        if report.checked_at != checked_at:
            raise ValueError("hosted verification record time does not match report")
        authorization.assert_valid_contract()
        if not plan.has_valid_content_hash():
            raise ValueError("hosted verification record plan is invalid")
        if not authorization.has_valid_content_hash():
            raise ValueError("hosted verification record authorization is invalid")
        if report.plan_sha256 != plan.content_sha256:
            raise ValueError("hosted verification record plan does not match report")
        if report.authorization_sha256 != authorization.content_sha256:
            raise ValueError(
                "hosted verification record authorization does not match report"
            )
        record_version = "hosted-verification-record.v1"
        operator_sha256 = _content_sha256({"operator_id": authorization.operator_id})
        subject_manifest_sha256 = _content_sha256(
            {
                "owner_subject_id": authorization.owner_subject_id,
                "unrelated_subject_id": authorization.unrelated_subject_id,
                "audit_subject_id": authorization.audit_subject_id,
            }
        )
        content = cls._content(
            record_version=record_version,
            issue_id=authorization.issue_id,
            database_scope=authorization.database_scope,
            plan_version=plan.plan_version,
            plan_sha256=plan.content_sha256,
            migration_manifest_sha256=plan.migration_manifest_sha256,
            target_manifest_sha256=plan.target_manifest_sha256,
            authorization_sha256=authorization.content_sha256,
            operator_sha256=operator_sha256,
            subject_manifest_sha256=subject_manifest_sha256,
            checked_at=checked_at,
            passed=report.passed,
            blocking_reason_codes=report.blocking_reason_codes,
            probe_results=report.probe_results,
        )
        return cls(
            record_version=record_version,
            issue_id=authorization.issue_id,
            database_scope=authorization.database_scope,
            plan_version=plan.plan_version,
            plan_sha256=plan.content_sha256,
            migration_manifest_sha256=plan.migration_manifest_sha256,
            target_manifest_sha256=plan.target_manifest_sha256,
            authorization_sha256=authorization.content_sha256,
            operator_sha256=operator_sha256,
            subject_manifest_sha256=subject_manifest_sha256,
            checked_at=checked_at,
            passed=report.passed,
            blocking_reason_codes=report.blocking_reason_codes,
            probe_results=report.probe_results,
            content_sha256=_content_sha256(content),
        )

    @staticmethod
    def _content(
        *,
        record_version: str,
        issue_id: str,
        database_scope: str,
        plan_version: str,
        plan_sha256: str,
        migration_manifest_sha256: str,
        target_manifest_sha256: str,
        authorization_sha256: str,
        operator_sha256: str,
        subject_manifest_sha256: str,
        checked_at: datetime,
        passed: bool,
        blocking_reason_codes: tuple[str, ...],
        probe_results: tuple[HostedVerificationProbeResult, ...],
    ) -> dict[str, object]:
        return {
            "record_version": record_version,
            "issue_id": issue_id,
            "database_scope": database_scope,
            "plan_version": plan_version,
            "plan_sha256": plan_sha256,
            "migration_manifest_sha256": migration_manifest_sha256,
            "target_manifest_sha256": target_manifest_sha256,
            "authorization_sha256": authorization_sha256,
            "operator_sha256": operator_sha256,
            "subject_manifest_sha256": subject_manifest_sha256,
            "checked_at": checked_at.isoformat(),
            "passed": passed,
            "blocking_reason_codes": list(blocking_reason_codes),
            "probe_results": [result.as_dict() for result in probe_results],
        }

    def has_valid_content_hash(self) -> bool:
        return self.content_sha256 == _content_sha256(
            self._content(
                record_version=self.record_version,
                issue_id=self.issue_id,
                database_scope=self.database_scope,
                plan_version=self.plan_version,
                plan_sha256=self.plan_sha256,
                migration_manifest_sha256=self.migration_manifest_sha256,
                target_manifest_sha256=self.target_manifest_sha256,
                authorization_sha256=self.authorization_sha256,
                operator_sha256=self.operator_sha256,
                subject_manifest_sha256=self.subject_manifest_sha256,
                checked_at=self.checked_at,
                passed=self.passed,
                blocking_reason_codes=self.blocking_reason_codes,
                probe_results=self.probe_results,
            )
        )

    def as_dict(self) -> dict[str, object]:
        return {
            **self._content(
                record_version=self.record_version,
                issue_id=self.issue_id,
                database_scope=self.database_scope,
                plan_version=self.plan_version,
                plan_sha256=self.plan_sha256,
                migration_manifest_sha256=self.migration_manifest_sha256,
                target_manifest_sha256=self.target_manifest_sha256,
                authorization_sha256=self.authorization_sha256,
                operator_sha256=self.operator_sha256,
                subject_manifest_sha256=self.subject_manifest_sha256,
                checked_at=self.checked_at,
                passed=self.passed,
                blocking_reason_codes=self.blocking_reason_codes,
                probe_results=self.probe_results,
            ),
            "content_sha256": self.content_sha256,
        }


class HostedDatabaseVerificationPort(Protocol):
    def run_database_probes(
        self,
        plan: HostedVerificationPlan,
        authorization: HostedVerificationAuthorization,
    ) -> tuple[HostedVerificationProbeResult, ...]: ...


class HostedAdvisorVerificationPort(Protocol):
    def run_advisor_probes(
        self,
        plan: HostedVerificationPlan,
        authorization: HostedVerificationAuthorization,
    ) -> tuple[HostedVerificationProbeResult, ...]: ...


class HostedVerificationHarness:
    def __init__(
        self,
        *,
        database: HostedDatabaseVerificationPort,
        advisor: HostedAdvisorVerificationPort,
    ) -> None:
        self.database = database
        self.advisor = advisor

    def run(
        self,
        *,
        plan: HostedVerificationPlan,
        authorization: HostedVerificationAuthorization | None,
        current_turn_id: str,
        checked_at: datetime,
    ) -> HostedVerificationReport:
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            return HostedVerificationReport(
                passed=False,
                blocking_reason_codes=("verification_time_invalid",),
                probe_results=(),
                checked_at=checked_at,
            )
        if not plan.has_valid_content_hash():
            return HostedVerificationReport(
                passed=False,
                blocking_reason_codes=("plan_content_hash_mismatch",),
                probe_results=(),
                checked_at=checked_at,
            )
        if authorization is None:
            return HostedVerificationReport(
                passed=False,
                blocking_reason_codes=("authorization_manifest_missing",),
                probe_results=(),
                checked_at=checked_at,
            )
        try:
            authorization.assert_valid_contract()
        except ValueError:
            return HostedVerificationReport(
                passed=False,
                blocking_reason_codes=("authorization_contract_invalid",),
                probe_results=(),
                checked_at=checked_at,
            )
        if not authorization.has_valid_content_hash():
            return HostedVerificationReport(
                passed=False,
                blocking_reason_codes=("authorization_content_hash_mismatch",),
                probe_results=(),
                checked_at=checked_at,
            )
        if authorization.turn_id != current_turn_id:
            return HostedVerificationReport(
                passed=False,
                blocking_reason_codes=("authorization_not_current_turn",),
                probe_results=(),
                checked_at=checked_at,
            )
        if checked_at < authorization.issued_at:
            return HostedVerificationReport(
                passed=False,
                blocking_reason_codes=("authorization_not_yet_valid",),
                probe_results=(),
                checked_at=checked_at,
            )
        if checked_at >= authorization.expires_at:
            return HostedVerificationReport(
                passed=False,
                blocking_reason_codes=("authorization_expired",),
                probe_results=(),
                checked_at=checked_at,
            )
        if authorization.authorized_scopes != plan.required_scopes():
            return HostedVerificationReport(
                passed=False,
                blocking_reason_codes=("authorization_scope_mismatch",),
                probe_results=(),
                checked_at=checked_at,
            )
        try:
            database_results = tuple(
                self.database.run_database_probes(plan, authorization)
            )
        except Exception:
            return HostedVerificationReport(
                passed=False,
                blocking_reason_codes=("database_probe_transport_failed",),
                probe_results=(),
                checked_at=checked_at,
                plan_sha256=plan.content_sha256,
                authorization_sha256=authorization.content_sha256,
            )
        if any(
            not isinstance(result, HostedVerificationProbeResult)
            for result in database_results
        ):
            return HostedVerificationReport(
                passed=False,
                blocking_reason_codes=("probe_result_contract_invalid",),
                probe_results=(),
                checked_at=checked_at,
                plan_sha256=plan.content_sha256,
                authorization_sha256=authorization.content_sha256,
            )
        try:
            advisor_results = tuple(
                self.advisor.run_advisor_probes(plan, authorization)
            )
        except Exception:
            return HostedVerificationReport(
                passed=False,
                blocking_reason_codes=("advisor_probe_transport_failed",),
                probe_results=database_results,
                checked_at=checked_at,
                plan_sha256=plan.content_sha256,
                authorization_sha256=authorization.content_sha256,
            )
        received = database_results + advisor_results
        if any(
            not isinstance(result, HostedVerificationProbeResult) for result in received
        ):
            return HostedVerificationReport(
                passed=False,
                blocking_reason_codes=("probe_result_contract_invalid",),
                probe_results=(),
                checked_at=checked_at,
                plan_sha256=plan.content_sha256,
                authorization_sha256=authorization.content_sha256,
            )
        by_id = {result.probe_id: result for result in received}
        if len(by_id) != len(received) or set(by_id) != {
            probe.probe_id for probe in plan.probes
        }:
            return HostedVerificationReport(
                passed=False,
                blocking_reason_codes=("probe_result_set_mismatch",),
                probe_results=(),
                checked_at=checked_at,
                plan_sha256=plan.content_sha256,
                authorization_sha256=authorization.content_sha256,
            )
        ordered_results = tuple(by_id[probe.probe_id] for probe in plan.probes)
        if any(
            result.category != probe.category
            for probe, result in zip(plan.probes, ordered_results, strict=True)
        ):
            return HostedVerificationReport(
                passed=False,
                blocking_reason_codes=("probe_result_category_mismatch",),
                probe_results=(),
                checked_at=checked_at,
                plan_sha256=plan.content_sha256,
                authorization_sha256=authorization.content_sha256,
            )
        contract_failures = tuple(
            f"probe_contract_mismatch:{probe.probe_id}"
            for probe, result in zip(plan.probes, ordered_results, strict=True)
            if (
                probe.expected_result_code is not None
                and result.result_code != probe.expected_result_code
            )
            or (
                probe.expected_count is not None
                and result.count != probe.expected_count
            )
        )
        artifact_failures = tuple(
            f"probe_artifact_hash_mismatch:{result.probe_id}"
            for result in ordered_results
            if (
                result.category == "migration_history"
                and result.artifact_sha256 != plan.migration_manifest_sha256
            )
            or (
                result.category == "owner_isolation"
                and result.artifact_sha256 != plan.target_manifest_sha256
            )
        )
        failed = tuple(
            f"probe_failed:{result.probe_id}"
            for result in ordered_results
            if not result.passed
        )
        blocking_reasons = contract_failures + artifact_failures + failed
        return HostedVerificationReport(
            passed=not blocking_reasons,
            blocking_reason_codes=blocking_reasons,
            probe_results=ordered_results,
            checked_at=checked_at,
            plan_sha256=plan.content_sha256,
            authorization_sha256=authorization.content_sha256,
        )


__all__ = [
    "HostedVerificationHarness",
    "HostedAdvisorVerificationPort",
    "HostedVerificationAuthorization",
    "HostedDatabaseVerificationPort",
    "HostedVerificationPlan",
    "HostedVerificationProbe",
    "HostedVerificationProbeResult",
    "HostedVerificationRecord",
    "HostedVerificationReport",
    "HostedMigrationManifestEntry",
    "IROS_HOSTED_VERIFICATION_TARGETS",
    "build_default_iros_hosted_verification_plan",
    "build_hosted_verification_plan",
    "build_matching_offline_probe_results",
]
