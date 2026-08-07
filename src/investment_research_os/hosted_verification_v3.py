from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from investment_research_os.hosted_verification import (
    IROS_REQUIRED_HOSTED_PROBE_IDS,
    HostedVerificationAuthorization,
    HostedVerificationPlan,
    build_default_iros_hosted_verification_plan,
)
from investment_research_os.migration_audit import strip_sql_comments_and_literals


_IDENTITY = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+")
_IROS_OBJECT = re.compile(r"iros_[a-z0-9_]+")
_TRANSPORT_OWNERS = frozenset({"database", "advisor"})
_OPERATIONS = frozenset(
    {
        "count_rows",
        "attempt_insert",
        "attempt_update",
        "read_migration_history",
        "read_grants",
        "read_view_security",
        "read_audit_events",
        "read_advisor_findings",
        "read_raw_provider_payload",
    }
)
_SUBJECT_ROLES = frozenset({"owner", "unrelated", "anonymous", "audit_permitted"})
_TARGET_OWNER_ROLES = frozenset({"owner", "unrelated", "system"})
_CLEANUP_RULES = frozenset({"none", "transaction_rollback"})
_ROLLBACK_ASSERTIONS = frozenset({"not_required", "required_and_verified"})


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class HostedProbeFixture:
    fixture_id: str
    setup_state: str
    row_identity: str
    target_owner_role: str
    cleanup_rule: str
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        fixture_id: str,
        setup_state: str,
        row_identity: str,
        target_owner_role: str,
        cleanup_rule: str,
    ) -> HostedProbeFixture:
        if _IDENTITY.fullmatch(fixture_id) is None:
            raise ValueError("hosted verification fixture ID is invalid")
        if not setup_state.strip() or not row_identity.strip():
            raise ValueError("hosted verification fixture state is invalid")
        if target_owner_role not in _TARGET_OWNER_ROLES:
            raise ValueError("hosted verification fixture owner role is invalid")
        if cleanup_rule not in _CLEANUP_RULES:
            raise ValueError("hosted verification fixture cleanup rule is invalid")
        content = {
            "fixture_id": fixture_id,
            "setup_state": setup_state,
            "row_identity": row_identity,
            "target_owner_role": target_owner_role,
            "cleanup_rule": cleanup_rule,
        }
        return cls(**content, content_sha256=_sha256(content))

    def has_valid_content_hash(self) -> bool:
        return self.content_sha256 == _sha256(
            {
                "fixture_id": self.fixture_id,
                "setup_state": self.setup_state,
                "row_identity": self.row_identity,
                "target_owner_role": self.target_owner_role,
                "cleanup_rule": self.cleanup_rule,
            }
        )


@dataclass(frozen=True, slots=True)
class HostedProbeDispatch:
    probe_id: str
    transport_owner: str
    operation: str
    target_objects: tuple[str, ...]
    subject_role: str
    fixture_id: str
    mutation_field: str | None
    expected_constraint: str | None
    rollback_assertion: str
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        probe_id: str,
        transport_owner: str,
        operation: str,
        target_objects: tuple[str, ...],
        subject_role: str,
        fixture_id: str,
        mutation_field: str | None,
        expected_constraint: str | None,
        rollback_assertion: str,
    ) -> HostedProbeDispatch:
        if _IDENTITY.fullmatch(probe_id) is None:
            raise ValueError("hosted verification dispatch probe ID is invalid")
        if transport_owner not in _TRANSPORT_OWNERS:
            raise ValueError("hosted verification dispatch owner is invalid")
        if operation not in _OPERATIONS:
            raise ValueError("hosted verification dispatch operation is invalid")
        if transport_owner == "advisor" and operation != "read_advisor_findings":
            raise ValueError(
                "hosted verification advisor dispatch operation is invalid"
            )
        if transport_owner == "database" and operation == "read_advisor_findings":
            raise ValueError(
                "hosted verification database dispatch operation is invalid"
            )
        targetless = operation in {
            "read_migration_history",
            "read_advisor_findings",
        }
        if (
            (not target_objects and not targetless)
            or (target_objects and targetless)
            or len(set(target_objects)) != len(target_objects)
            or any(_IROS_OBJECT.fullmatch(item) is None for item in target_objects)
        ):
            raise ValueError("hosted verification dispatch targets are invalid")
        if subject_role not in _SUBJECT_ROLES:
            raise ValueError("hosted verification dispatch subject role is invalid")
        if _IDENTITY.fullmatch(fixture_id) is None:
            raise ValueError("hosted verification dispatch fixture ID is invalid")
        if rollback_assertion not in _ROLLBACK_ASSERTIONS:
            raise ValueError("hosted verification rollback assertion is invalid")
        mutating = operation in {"attempt_insert", "attempt_update"}
        if mutating and (
            rollback_assertion != "required_and_verified"
            or not mutation_field
            or not expected_constraint
        ):
            raise ValueError(
                "hosted verification mutating dispatch requires verified rollback"
            )
        if not mutating and (
            rollback_assertion != "not_required"
            or mutation_field is not None
            or expected_constraint is not None
        ):
            raise ValueError("hosted verification read dispatch cannot mutate")
        ordered_targets = tuple(sorted(target_objects))
        content = {
            "probe_id": probe_id,
            "transport_owner": transport_owner,
            "operation": operation,
            "target_objects": list(ordered_targets),
            "subject_role": subject_role,
            "fixture_id": fixture_id,
            "mutation_field": mutation_field,
            "expected_constraint": expected_constraint,
            "rollback_assertion": rollback_assertion,
        }
        return cls(
            probe_id=probe_id,
            transport_owner=transport_owner,
            operation=operation,
            target_objects=ordered_targets,
            subject_role=subject_role,
            fixture_id=fixture_id,
            mutation_field=mutation_field,
            expected_constraint=expected_constraint,
            rollback_assertion=rollback_assertion,
            content_sha256=_sha256(content),
        )

    def has_valid_content_hash(self) -> bool:
        return self.content_sha256 == _sha256(
            {
                "probe_id": self.probe_id,
                "transport_owner": self.transport_owner,
                "operation": self.operation,
                "target_objects": list(self.target_objects),
                "subject_role": self.subject_role,
                "fixture_id": self.fixture_id,
                "mutation_field": self.mutation_field,
                "expected_constraint": self.expected_constraint,
                "rollback_assertion": self.rollback_assertion,
            }
        )


@dataclass(frozen=True, slots=True)
class HostedVerificationExecutionContract:
    contract_version: str
    plan_sha256: str
    migration_manifest_sha256: str
    plan_target_manifest_sha256: str
    execution_target_manifest_sha256: str
    dispatch_registry_sha256: str
    fixture_set_sha256: str
    required_scopes: tuple[str, ...]
    dispatches: tuple[HostedProbeDispatch, ...]
    fixtures: tuple[HostedProbeFixture, ...]
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        plan: HostedVerificationPlan,
        dispatches: tuple[HostedProbeDispatch, ...],
        fixtures: tuple[HostedProbeFixture, ...],
    ) -> HostedVerificationExecutionContract:
        if not plan.has_valid_content_hash():
            raise ValueError("hosted verification v3 plan hash is invalid")
        ordered_dispatches = tuple(sorted(dispatches, key=lambda item: item.probe_id))
        ordered_fixtures = tuple(sorted(fixtures, key=lambda item: item.fixture_id))
        if any(not item.has_valid_content_hash() for item in ordered_dispatches):
            raise ValueError("hosted verification v3 dispatch hash is invalid")
        if any(not item.has_valid_content_hash() for item in ordered_fixtures):
            raise ValueError("hosted verification v3 fixture hash is invalid")
        if len({item.probe_id for item in ordered_dispatches}) != len(
            ordered_dispatches
        ):
            raise ValueError("hosted verification v3 dispatch IDs must be unique")
        if {item.probe_id for item in ordered_dispatches} != {
            probe.probe_id for probe in plan.probes
        }:
            raise ValueError("hosted verification v3 dispatch coverage is invalid")
        if len({item.fixture_id for item in ordered_fixtures}) != len(ordered_fixtures):
            raise ValueError("hosted verification v3 fixture IDs must be unique")
        fixture_ids = {item.fixture_id for item in ordered_fixtures}
        if any(item.fixture_id not in fixture_ids for item in ordered_dispatches):
            raise ValueError("hosted verification v3 dispatch fixture is unavailable")
        if fixture_ids != {item.fixture_id for item in ordered_dispatches}:
            raise ValueError("hosted verification v3 fixture coverage is invalid")
        fixtures_by_id = {item.fixture_id: item for item in ordered_fixtures}
        if any(
            item.operation in {"attempt_insert", "attempt_update"}
            and fixtures_by_id[item.fixture_id].cleanup_rule != "transaction_rollback"
            for item in ordered_dispatches
        ):
            raise ValueError(
                "hosted verification v3 mutating fixture cleanup is invalid"
            )
        dispatch_hash = _sha256([item.content_sha256 for item in ordered_dispatches])
        fixture_hash = _sha256([item.content_sha256 for item in ordered_fixtures])
        execution_targets = tuple(
            sorted(
                {
                    target
                    for dispatch in ordered_dispatches
                    for target in dispatch.target_objects
                }
            )
        )
        execution_target_hash = _sha256(list(execution_targets))
        version = "hosted-verification-execution-contract.v3"
        content = {
            "contract_version": version,
            "plan_sha256": plan.content_sha256,
            "migration_manifest_sha256": plan.migration_manifest_sha256,
            "plan_target_manifest_sha256": plan.target_manifest_sha256,
            "execution_target_manifest_sha256": execution_target_hash,
            "dispatch_registry_sha256": dispatch_hash,
            "fixture_set_sha256": fixture_hash,
            "required_scopes": list(plan.required_scopes),
        }
        return cls(
            contract_version=version,
            plan_sha256=plan.content_sha256,
            migration_manifest_sha256=plan.migration_manifest_sha256,
            plan_target_manifest_sha256=plan.target_manifest_sha256,
            execution_target_manifest_sha256=execution_target_hash,
            dispatch_registry_sha256=dispatch_hash,
            fixture_set_sha256=fixture_hash,
            required_scopes=plan.required_scopes,
            dispatches=ordered_dispatches,
            fixtures=ordered_fixtures,
            content_sha256=_sha256(content),
        )

    def has_valid_content_hash(self) -> bool:
        if (
            self.contract_version != "hosted-verification-execution-contract.v3"
            or self.dispatches
            != tuple(sorted(self.dispatches, key=lambda item: item.probe_id))
            or self.fixtures
            != tuple(sorted(self.fixtures, key=lambda item: item.fixture_id))
            or len({item.probe_id for item in self.dispatches}) != len(self.dispatches)
            or len({item.fixture_id for item in self.fixtures}) != len(self.fixtures)
            or any(not item.has_valid_content_hash() for item in self.dispatches)
            or any(not item.has_valid_content_hash() for item in self.fixtures)
            or self.dispatch_registry_sha256
            != _sha256([item.content_sha256 for item in self.dispatches])
            or self.fixture_set_sha256
            != _sha256([item.content_sha256 for item in self.fixtures])
            or self.execution_target_manifest_sha256
            != _sha256(
                sorted(
                    {
                        target
                        for dispatch in self.dispatches
                        for target in dispatch.target_objects
                    }
                )
            )
        ):
            return False
        return self.content_sha256 == _sha256(
            {
                "contract_version": self.contract_version,
                "plan_sha256": self.plan_sha256,
                "migration_manifest_sha256": self.migration_manifest_sha256,
                "plan_target_manifest_sha256": self.plan_target_manifest_sha256,
                "execution_target_manifest_sha256": (
                    self.execution_target_manifest_sha256
                ),
                "dispatch_registry_sha256": self.dispatch_registry_sha256,
                "fixture_set_sha256": self.fixture_set_sha256,
                "required_scopes": list(self.required_scopes),
            }
        )

    @property
    def target_manifest_sha256(self) -> str:
        return self.execution_target_manifest_sha256


@dataclass(frozen=True, slots=True)
class HostedVerificationExecutionAuthorization:
    contract_version: str
    authorization_sha256: str
    plan_sha256: str
    migration_manifest_sha256: str
    plan_target_manifest_sha256: str
    target_manifest_sha256: str
    dispatch_registry_sha256: str
    fixture_set_sha256: str
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        authorization: HostedVerificationAuthorization,
        execution_contract: HostedVerificationExecutionContract,
    ) -> HostedVerificationExecutionAuthorization:
        authorization.assert_valid_contract()
        if not authorization.has_valid_content_hash():
            raise ValueError("hosted verification v3 authorization hash is invalid")
        if not execution_contract.has_valid_content_hash():
            raise ValueError("hosted verification v3 execution contract is invalid")
        if authorization.authorized_scopes != execution_contract.required_scopes:
            raise ValueError(
                "hosted verification v3 authorization scopes do not match execution contract"
            )
        version = "hosted-verification-execution-authorization.v3"
        content = {
            "contract_version": version,
            "authorization_sha256": authorization.content_sha256,
            "plan_sha256": execution_contract.plan_sha256,
            "migration_manifest_sha256": (execution_contract.migration_manifest_sha256),
            "plan_target_manifest_sha256": (
                execution_contract.plan_target_manifest_sha256
            ),
            "target_manifest_sha256": (
                execution_contract.execution_target_manifest_sha256
            ),
            "dispatch_registry_sha256": (execution_contract.dispatch_registry_sha256),
            "fixture_set_sha256": execution_contract.fixture_set_sha256,
        }
        return cls(**content, content_sha256=_sha256(content))

    def has_valid_content_hash(self) -> bool:
        return self.content_sha256 == _sha256(
            {
                "contract_version": self.contract_version,
                "authorization_sha256": self.authorization_sha256,
                "plan_sha256": self.plan_sha256,
                "migration_manifest_sha256": self.migration_manifest_sha256,
                "plan_target_manifest_sha256": self.plan_target_manifest_sha256,
                "target_manifest_sha256": self.target_manifest_sha256,
                "dispatch_registry_sha256": self.dispatch_registry_sha256,
                "fixture_set_sha256": self.fixture_set_sha256,
            }
        )


_MUTATION_TARGETS = {
    "research_run": "iros_research_runs",
    "grader_execution": "iros_grader_executions",
    "committee": "iros_committee_results",
    "memo": "iros_committee_memos",
    "thesis": "iros_thesis_versions",
    "operator_decision": "iros_operator_decisions",
    "command": "iros_workflow_commands",
    "market_series": "iros_market_series",
}
_MUTATION_FIELDS = {
    "research_run": "status",
    "grader_execution": "execution_state",
    "committee": "committee_status",
    "memo": "requested_disposition",
    "thesis": "final_disposition",
    "operator_decision": "rationale",
    "command": "state",
    "market_series": "currency",
}


def _declared_iros_objects(migration_paths: tuple[Path, ...]) -> frozenset[str]:
    declared: set[str] = set()
    pattern = re.compile(
        r"\bcreate\s+(?:or\s+replace\s+)?(?:table|view|function)\s+"
        r"(?:if\s+not\s+exists\s+)?public\.(iros_[a-z0-9_]+)\b",
        re.IGNORECASE,
    )
    for path in migration_paths:
        sql = strip_sql_comments_and_literals(path.read_text())
        declared.update(match.group(1).lower() for match in pattern.finditer(sql))
    return frozenset(declared)


def _fixture(
    fixture_id: str,
    *,
    setup_state: str,
    row_identity: str,
    owner_role: str,
    cleanup_rule: str = "none",
) -> HostedProbeFixture:
    return HostedProbeFixture.freeze(
        fixture_id=fixture_id,
        setup_state=setup_state,
        row_identity=row_identity,
        target_owner_role=owner_role,
        cleanup_rule=cleanup_rule,
    )


def _default_fixtures() -> tuple[HostedProbeFixture, ...]:
    fixtures = [
        _fixture(
            "fixture.migration_history",
            setup_state="reviewed_migration_batch",
            row_identity="migration_batch",
            owner_role="system",
        ),
        _fixture(
            "fixture.owner_graph",
            setup_state="seeded_owner_graph",
            row_identity="owner_graph",
            owner_role="owner",
        ),
        _fixture(
            "fixture.raw_payload",
            setup_state="seeded_raw_provider_payload",
            row_identity="raw_provider_payload",
            owner_role="owner",
        ),
        _fixture(
            "fixture.advisor_snapshot",
            setup_state="current_advisor_snapshot",
            row_identity="advisor_snapshot",
            owner_role="system",
        ),
    ]
    for prefix in ("immutable", "duplicate"):
        for identity in _MUTATION_TARGETS:
            fixtures.append(
                _fixture(
                    f"fixture.{prefix}_{identity}",
                    setup_state=f"{prefix}_probe_row",
                    row_identity=f"{prefix}_{identity}_row",
                    owner_role="owner",
                    cleanup_rule="transaction_rollback",
                )
            )
    for state in (
        "missing",
        "invalid",
        "stale",
        "pre_material_evidence",
        "indeterminate",
    ):
        fixtures.append(
            _fixture(
                f"fixture.valuation_{state}",
                setup_state=f"valuation_{state}_scenario",
                row_identity=f"valuation_{state}_run",
                owner_role="owner",
                cleanup_rule="transaction_rollback",
            )
        )
    return tuple(fixtures)


def _default_dispatches(
    plan: HostedVerificationPlan,
) -> tuple[HostedProbeDispatch, ...]:
    access_targets = plan.target_objects
    view_targets = tuple(
        target for target in access_targets if target.startswith("iros_v_")
    )
    dispatches: list[HostedProbeDispatch] = []
    for probe_id in IROS_REQUIRED_HOSTED_PROBE_IDS:
        common: dict[str, object] = {
            "probe_id": probe_id,
            "transport_owner": "database",
            "mutation_field": None,
            "expected_constraint": None,
            "rollback_assertion": "not_required",
        }
        if probe_id == "migration.linked_history":
            common.update(
                operation="read_migration_history",
                target_objects=(),
                subject_role="audit_permitted",
                fixture_id="fixture.migration_history",
            )
        elif probe_id == "access.owner":
            common.update(
                operation="count_rows",
                target_objects=access_targets,
                subject_role="owner",
                fixture_id="fixture.owner_graph",
            )
        elif probe_id == "access.unrelated_denied":
            common.update(
                operation="count_rows",
                target_objects=access_targets,
                subject_role="unrelated",
                fixture_id="fixture.owner_graph",
            )
        elif probe_id == "access.anonymous_denied":
            common.update(
                operation="count_rows",
                target_objects=access_targets,
                subject_role="anonymous",
                fixture_id="fixture.owner_graph",
            )
        elif probe_id == "access.least_privilege_grants":
            common.update(
                operation="read_grants",
                target_objects=access_targets,
                subject_role="audit_permitted",
                fixture_id="fixture.owner_graph",
            )
        elif probe_id == "access.security_invoker_views":
            common.update(
                operation="read_view_security",
                target_objects=view_targets,
                subject_role="audit_permitted",
                fixture_id="fixture.owner_graph",
            )
        elif probe_id.startswith("raw_audit."):
            raw_subjects = {
                "raw_audit.ordinary_denied": "owner",
                "raw_audit.owner_permitted": "audit_permitted",
                "raw_audit.cross_owner_denied": "unrelated",
                "raw_audit.access_event": "audit_permitted",
            }
            common.update(
                operation=(
                    "read_audit_events"
                    if probe_id == "raw_audit.access_event"
                    else "read_raw_provider_payload"
                ),
                target_objects=(
                    ("iros_raw_provider_payload_access_events",)
                    if probe_id == "raw_audit.access_event"
                    else ("iros_read_raw_provider_payload",)
                ),
                subject_role=raw_subjects[probe_id],
                fixture_id="fixture.raw_payload",
            )
        elif probe_id == "advisor.iros_findings":
            common.update(
                transport_owner="advisor",
                operation="read_advisor_findings",
                target_objects=(),
                subject_role="audit_permitted",
                fixture_id="fixture.advisor_snapshot",
            )
        elif probe_id.startswith(("immutable.", "duplicate.")):
            prefix, identity = probe_id.split(".", 1)
            common.update(
                operation=(
                    "attempt_update" if prefix == "immutable" else "attempt_insert"
                ),
                target_objects=(_MUTATION_TARGETS[identity],),
                subject_role="audit_permitted",
                fixture_id=f"fixture.{prefix}_{identity}",
                mutation_field=_MUTATION_FIELDS[identity],
                expected_constraint=f"{prefix}_{identity}_enforced",
                rollback_assertion="required_and_verified",
            )
        elif probe_id.startswith("valuation."):
            state = probe_id.split(".", 1)[1]
            common.update(
                operation="attempt_insert",
                target_objects=("iros_readiness_gate_results",),
                subject_role="audit_permitted",
                fixture_id=f"fixture.valuation_{state}",
                mutation_field="final_disposition",
                expected_constraint="aligned_valuation_snapshot_required",
                rollback_assertion="required_and_verified",
            )
        else:  # pragma: no cover - closed required-probe registry above
            raise ValueError("hosted verification v3 probe is unmapped")
        dispatches.append(HostedProbeDispatch.freeze(**common))
    return tuple(dispatches)


def build_default_iros_hosted_execution_contract(
    *,
    migration_paths: tuple[Path, ...],
) -> HostedVerificationExecutionContract:
    plan = build_default_iros_hosted_verification_plan(
        migration_paths=migration_paths,
    )
    dispatches = _default_dispatches(plan)
    declared_objects = _declared_iros_objects(migration_paths)
    execution_targets = {
        target for dispatch in dispatches for target in dispatch.target_objects
    }
    missing_targets = tuple(sorted(execution_targets - declared_objects))
    if missing_targets:
        raise ValueError(
            "hosted verification v3 dispatch target is absent from reviewed migrations: "
            + ",".join(missing_targets)
        )
    return HostedVerificationExecutionContract.freeze(
        plan=plan,
        dispatches=dispatches,
        fixtures=_default_fixtures(),
    )


__all__ = [
    "HostedProbeDispatch",
    "HostedProbeFixture",
    "HostedVerificationExecutionAuthorization",
    "HostedVerificationExecutionContract",
    "build_default_iros_hosted_execution_contract",
]
