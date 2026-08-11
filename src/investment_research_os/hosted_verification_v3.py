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
from investment_research_os.iros_constraint_index import (
    IrosConstraintIndex,
    build_iros_constraint_index,
)
from investment_research_os.iros_object_inventory import build_iros_object_inventory


_IDENTITY = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+")
_IROS_OBJECT = re.compile(r"iros_[a-z0-9_]+")
_TRANSPORT_OWNERS = frozenset({"database", "advisor"})
_OPERATIONS = frozenset(
    {
        "count_rows",
        "read_access_surface",
        "attempt_duplicate_insert",
        "attempt_invalid_insert",
        "attempt_update",
        "read_migration_history",
        "read_grants",
        "read_view_security",
        "read_advisor_findings",
        "read_raw_provider_payload",
        "assert_raw_access_residue",
    }
)
_SUBJECT_ROLES = frozenset({"owner", "unrelated", "anonymous", "audit_permitted"})
_TARGET_OWNER_ROLES = frozenset({"owner", "unrelated", "system"})
_CLEANUP_RULES = frozenset({"none", "transaction_rollback"})
_ROLLBACK_ASSERTIONS = frozenset({"not_required", "required_and_verified"})
_SETUP_STATES = frozenset(
    {
        "advisor_snapshot",
        "duplicate_key_row",
        "finalized_row",
        "invalid_valuation_row",
        "migration_batch",
        "owner_graph",
        "raw_provider_payload",
    }
)
# Static RPC/grant presence is not executable reachability. Add an ID only when
# the production worker maps that exact dispatch to its authorization-bound port.
_RUNNABLE_PRIVILEGED_PROBE_IDS: frozenset[str] = frozenset()


class HostedVerificationContractError(ValueError):
    def __init__(
        self,
        reason_code: str,
        *,
        blocking_probe_ids: tuple[str, ...] = (),
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.blocking_probe_ids = tuple(sorted(set(blocking_probe_ids)))


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
        if setup_state not in _SETUP_STATES or not row_identity.strip():
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
    conflict_key: tuple[str, ...] | None
    privileged_rpc: str | None
    expected_constraint: str | None
    residue_assertion: str | None
    residue_source_probe_id: str | None
    external_scope_reason_code: str | None
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
        conflict_key: tuple[str, ...] | None = None,
        privileged_rpc: str | None = None,
        expected_constraint: str | None,
        residue_assertion: str | None = None,
        residue_source_probe_id: str | None = None,
        external_scope_reason_code: str | None = None,
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
        mutating = operation in {
            "attempt_duplicate_insert",
            "attempt_invalid_insert",
            "attempt_update",
        }
        if privileged_rpc is not None and (
            not mutating
            or privileged_rpc != "iros_run_hosted_negative_probe"
            or probe_id != "immutable.research_run"
            or subject_role != "audit_permitted"
        ):
            raise ValueError("hosted verification privileged RPC is invalid")
        ordered_conflict_key = (
            tuple(sorted(set(conflict_key))) if conflict_key is not None else None
        )
        if ordered_conflict_key is not None and (
            not ordered_conflict_key
            or len(ordered_conflict_key) != len(conflict_key or ())
            or any(
                re.fullmatch(r"[a-z][a-z0-9_]*", field) is None
                for field in ordered_conflict_key
            )
        ):
            raise ValueError("hosted verification conflict key is invalid")
        if mutating and (
            rollback_assertion != "required_and_verified" or not expected_constraint
        ):
            raise ValueError(
                "hosted verification mutating dispatch requires verified rollback"
            )
        if operation == "attempt_update" and (
            not mutation_field or ordered_conflict_key is not None
        ):
            raise ValueError("hosted verification update dispatch is invalid")
        if operation == "attempt_duplicate_insert" and (
            mutation_field is not None or ordered_conflict_key is None
        ):
            raise ValueError("hosted verification duplicate dispatch is invalid")
        if operation == "attempt_invalid_insert" and (
            mutation_field is not None or ordered_conflict_key is not None
        ):
            raise ValueError("hosted verification invalid insert dispatch is invalid")
        if not mutating and (
            rollback_assertion != "not_required"
            or mutation_field is not None
            or ordered_conflict_key is not None
            or expected_constraint is not None
        ):
            raise ValueError("hosted verification read dispatch cannot mutate")
        if (operation == "assert_raw_access_residue") != (
            residue_assertion == "access_audit_event_id_and_accessed_at"
        ):
            raise ValueError("hosted verification residue assertion is invalid")
        if (operation == "assert_raw_access_residue") != (
            residue_source_probe_id is not None
            and _IDENTITY.fullmatch(residue_source_probe_id) is not None
        ):
            raise ValueError("hosted verification residue source is invalid")
        if (operation == "read_migration_history") != (
            external_scope_reason_code == "fixed_supabase_migration_history"
        ):
            raise ValueError("hosted verification external scope reason is invalid")
        ordered_targets = tuple(sorted(target_objects))
        content = {
            "probe_id": probe_id,
            "transport_owner": transport_owner,
            "operation": operation,
            "target_objects": list(ordered_targets),
            "subject_role": subject_role,
            "fixture_id": fixture_id,
            "mutation_field": mutation_field,
            "conflict_key": (
                list(ordered_conflict_key) if ordered_conflict_key is not None else None
            ),
            "privileged_rpc": privileged_rpc,
            "expected_constraint": expected_constraint,
            "residue_assertion": residue_assertion,
            "residue_source_probe_id": residue_source_probe_id,
            "external_scope_reason_code": external_scope_reason_code,
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
            conflict_key=ordered_conflict_key,
            privileged_rpc=privileged_rpc,
            expected_constraint=expected_constraint,
            residue_assertion=residue_assertion,
            residue_source_probe_id=residue_source_probe_id,
            external_scope_reason_code=external_scope_reason_code,
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
                "conflict_key": (
                    list(self.conflict_key) if self.conflict_key is not None else None
                ),
                "privileged_rpc": self.privileged_rpc,
                "expected_constraint": self.expected_constraint,
                "residue_assertion": self.residue_assertion,
                "residue_source_probe_id": self.residue_source_probe_id,
                "external_scope_reason_code": self.external_scope_reason_code,
                "rollback_assertion": self.rollback_assertion,
            }
        )

    @property
    def execution_targets(self) -> tuple[str, ...]:
        targets = set(self.target_objects)
        if self.privileged_rpc is not None:
            targets.add(self.privileged_rpc)
        return tuple(sorted(targets))


@dataclass(frozen=True, slots=True)
class HostedVerificationExecutionContract:
    contract_version: str
    plan_sha256: str
    migration_manifest_sha256: str
    plan_target_manifest_sha256: str
    execution_target_manifest_sha256: str
    dispatch_registry_sha256: str
    fixture_set_sha256: str
    inventory_sha256: str
    constraint_index_sha256: str
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
        inventory_sha256: str,
        constraint_index_sha256: str,
    ) -> HostedVerificationExecutionContract:
        if not plan.has_valid_content_hash():
            raise ValueError("hosted verification v3 plan hash is invalid")
        ordered_dispatches = tuple(sorted(dispatches, key=lambda item: item.probe_id))
        ordered_fixtures = tuple(sorted(fixtures, key=lambda item: item.fixture_id))
        if any(not item.has_valid_content_hash() for item in ordered_dispatches):
            raise ValueError("hosted verification v3 dispatch hash is invalid")
        if any(not item.has_valid_content_hash() for item in ordered_fixtures):
            raise ValueError("hosted verification v3 fixture hash is invalid")
        if any(
            re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (inventory_sha256, constraint_index_sha256)
        ):
            raise ValueError("hosted verification v3 schema hash is invalid")
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
        probes_by_id = {item.probe_id: item for item in plan.probes}
        dispatches_by_id = {item.probe_id: item for item in ordered_dispatches}
        for dispatch in ordered_dispatches:
            expected_count = probes_by_id[dispatch.probe_id].expected_count
            if (
                expected_count is not None
                and dispatch.target_objects
                and len(dispatch.target_objects) != expected_count
            ):
                raise ValueError(
                    "hosted verification v3 dispatch target count is invalid"
                )
            if dispatch.residue_source_probe_id is not None:
                source = dispatches_by_id.get(dispatch.residue_source_probe_id)
                if (
                    source is None
                    or source.operation != "read_raw_provider_payload"
                    or source.fixture_id != dispatch.fixture_id
                    or source.target_objects != dispatch.target_objects
                ):
                    raise ValueError(
                        "hosted verification v3 residue source binding is invalid"
                    )
        if any(
            item.operation
            in {
                "attempt_duplicate_insert",
                "attempt_invalid_insert",
                "attempt_update",
            }
            and fixtures_by_id[item.fixture_id].cleanup_rule != "transaction_rollback"
            for item in ordered_dispatches
        ):
            raise ValueError(
                "hosted verification v3 mutating fixture cleanup is invalid"
            )
        if any(
            item.probe_id.startswith("immutable.")
            and fixtures_by_id[item.fixture_id].setup_state != "finalized_row"
            for item in ordered_dispatches
        ):
            raise ValueError(
                "hosted verification v3 immutable fixture is not finalized"
            )
        if any(
            item.probe_id.startswith("duplicate.")
            and fixtures_by_id[item.fixture_id].setup_state != "duplicate_key_row"
            for item in ordered_dispatches
        ):
            raise ValueError(
                "hosted verification v3 duplicate fixture key is unavailable"
            )
        dispatch_hash = _sha256([item.content_sha256 for item in ordered_dispatches])
        fixture_hash = _sha256([item.content_sha256 for item in ordered_fixtures])
        execution_targets = tuple(
            sorted(
                {
                    target
                    for dispatch in ordered_dispatches
                    for target in dispatch.execution_targets
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
            "inventory_sha256": inventory_sha256,
            "constraint_index_sha256": constraint_index_sha256,
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
            inventory_sha256=inventory_sha256,
            constraint_index_sha256=constraint_index_sha256,
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
            or re.fullmatch(r"[0-9a-f]{64}", self.inventory_sha256) is None
            or re.fullmatch(r"[0-9a-f]{64}", self.constraint_index_sha256) is None
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
                        for target in dispatch.execution_targets
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
                "inventory_sha256": self.inventory_sha256,
                "constraint_index_sha256": self.constraint_index_sha256,
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
    execution_contract_sha256: str
    plan_sha256: str
    migration_manifest_sha256: str
    plan_target_manifest_sha256: str
    target_manifest_sha256: str
    dispatch_registry_sha256: str
    fixture_set_sha256: str
    inventory_sha256: str
    constraint_index_sha256: str
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
            "execution_contract_sha256": execution_contract.content_sha256,
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
            "inventory_sha256": execution_contract.inventory_sha256,
            "constraint_index_sha256": execution_contract.constraint_index_sha256,
        }
        return cls(**content, content_sha256=_sha256(content))

    def has_valid_content_hash(self) -> bool:
        return self.content_sha256 == _sha256(
            {
                "contract_version": self.contract_version,
                "authorization_sha256": self.authorization_sha256,
                "execution_contract_sha256": self.execution_contract_sha256,
                "plan_sha256": self.plan_sha256,
                "migration_manifest_sha256": self.migration_manifest_sha256,
                "plan_target_manifest_sha256": self.plan_target_manifest_sha256,
                "target_manifest_sha256": self.target_manifest_sha256,
                "dispatch_registry_sha256": self.dispatch_registry_sha256,
                "fixture_set_sha256": self.fixture_set_sha256,
                "inventory_sha256": self.inventory_sha256,
                "constraint_index_sha256": self.constraint_index_sha256,
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
    "research_run": "idempotency_key",
    "grader_execution": "execution_state",
    "committee": "committee_status",
    "memo": "requested_disposition",
    "thesis": "final_disposition",
    "operator_decision": "rationale",
    "command": "command_state",
    "market_series": "currency",
}

_IMMUTABILITY_ENFORCERS = {
    "research_run": "iros_research_runs_contract_immutable",
    "grader_execution": "iros_grader_executions_z_immutable",
    "committee": "iros_committee_results_z_immutable",
    "memo": "iros_committee_memos_immutable",
    "thesis": "iros_thesis_versions_z_immutable",
    "operator_decision": "iros_operator_decisions_z_immutable",
    "command": "iros_workflow_commands_z_immutable",
    "market_series": "iros_market_series_immutable",
}
_DUPLICATE_ENFORCERS = {
    "research_run": "iros_research_runs_operator_idempotency_unique",
    "grader_execution": "iros_grader_executions_key_unique",
    "committee": "iros_committee_results_run_unique",
    "memo": "iros_committee_memos_execution_unique",
    "thesis": "iros_thesis_versions_run_unique",
    "operator_decision": "iros_operator_decisions_idempotency_unique",
    "command": "iros_workflow_commands_event_type_unique",
    "market_series": "iros_market_series_content_unique",
}
_DUPLICATE_KEYS = {
    "research_run": ("operator_id", "idempotency_key"),
    "grader_execution": ("operator_id", "execution_key"),
    "committee": ("operator_id", "research_run_id"),
    "memo": ("operator_id", "synthesis_execution_id"),
    "thesis": ("operator_id", "research_run_id"),
    "operator_decision": ("operator_id", "idempotency_key"),
    "command": ("operator_id", "operator_decision_id", "command_type"),
    "market_series": ("operator_id", "security_id", "provider", "response_sha256"),
}


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
            setup_state="migration_batch",
            row_identity="migration_batch",
            owner_role="system",
        ),
        _fixture(
            "fixture.owner_graph",
            setup_state="owner_graph",
            row_identity="owner_graph",
            owner_role="owner",
        ),
        _fixture(
            "fixture.raw_payload",
            setup_state="raw_provider_payload",
            row_identity="raw_provider_payload",
            owner_role="owner",
        ),
        _fixture(
            "fixture.advisor_snapshot",
            setup_state="advisor_snapshot",
            row_identity="advisor_snapshot",
            owner_role="system",
        ),
    ]
    for prefix in ("immutable", "duplicate"):
        for identity in _MUTATION_TARGETS:
            fixtures.append(
                _fixture(
                    f"fixture.{prefix}_{identity}",
                    setup_state=(
                        "finalized_row"
                        if prefix == "immutable"
                        else "duplicate_key_row"
                    ),
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
                setup_state="invalid_valuation_row",
                row_identity=f"valuation_{state}_run",
                owner_role="owner",
                cleanup_rule="transaction_rollback",
            )
        )
    return tuple(fixtures)


def _default_dispatches(
    plan: HostedVerificationPlan,
    constraint_index: IrosConstraintIndex,
) -> tuple[HostedProbeDispatch, ...]:
    access_targets = plan.target_objects
    dispatches: list[HostedProbeDispatch] = []
    for probe_id in IROS_REQUIRED_HOSTED_PROBE_IDS:
        common: dict[str, object] = {
            "probe_id": probe_id,
            "transport_owner": "database",
            "mutation_field": None,
            "conflict_key": None,
            "privileged_rpc": None,
            "expected_constraint": None,
            "residue_assertion": None,
            "residue_source_probe_id": None,
            "external_scope_reason_code": None,
            "rollback_assertion": "not_required",
        }
        if probe_id == "migration.linked_history":
            common.update(
                operation="read_migration_history",
                target_objects=(),
                subject_role="audit_permitted",
                fixture_id="fixture.migration_history",
                external_scope_reason_code="fixed_supabase_migration_history",
            )
        elif probe_id == "access.owner":
            common.update(
                operation="read_access_surface",
                target_objects=access_targets,
                subject_role="owner",
                fixture_id="fixture.owner_graph",
            )
        elif probe_id == "access.unrelated_denied":
            common.update(
                operation="read_access_surface",
                target_objects=access_targets,
                subject_role="unrelated",
                fixture_id="fixture.owner_graph",
            )
        elif probe_id == "access.anonymous_denied":
            common.update(
                operation="read_access_surface",
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
                target_objects=access_targets,
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
                    "assert_raw_access_residue"
                    if probe_id == "raw_audit.access_event"
                    else "read_raw_provider_payload"
                ),
                target_objects=("iros_read_raw_provider_payload",),
                subject_role=raw_subjects[probe_id],
                fixture_id="fixture.raw_payload",
                residue_assertion=(
                    "access_audit_event_id_and_accessed_at"
                    if probe_id == "raw_audit.access_event"
                    else None
                ),
                residue_source_probe_id=(
                    "raw_audit.owner_permitted"
                    if probe_id == "raw_audit.access_event"
                    else None
                ),
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
            target = _MUTATION_TARGETS[identity]
            expected_constraint = (
                _IMMUTABILITY_ENFORCERS[identity]
                if prefix == "immutable"
                else _DUPLICATE_ENFORCERS[identity]
            )
            constraint_index.require_name(target, expected_constraint)
            common.update(
                operation=(
                    "attempt_update"
                    if prefix == "immutable"
                    else "attempt_duplicate_insert"
                ),
                target_objects=(target,),
                subject_role="audit_permitted",
                fixture_id=f"fixture.{prefix}_{identity}",
                mutation_field=(
                    _MUTATION_FIELDS[identity] if prefix == "immutable" else None
                ),
                conflict_key=(
                    _DUPLICATE_KEYS[identity] if prefix == "duplicate" else None
                ),
                privileged_rpc=(
                    "iros_run_hosted_negative_probe"
                    if probe_id == "immutable.research_run"
                    else None
                ),
                expected_constraint=expected_constraint,
                rollback_assertion="required_and_verified",
            )
        elif probe_id.startswith("valuation."):
            state = probe_id.split(".", 1)[1]
            target = "iros_readiness_gate_results"
            expected_constraint = "iros_readiness_gate_results_a_validate_insert"
            constraint_index.require_name(target, expected_constraint)
            common.update(
                operation="attempt_invalid_insert",
                target_objects=(target,),
                subject_role="audit_permitted",
                fixture_id=f"fixture.valuation_{state}",
                expected_constraint=expected_constraint,
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
    try:
        plan = build_default_iros_hosted_verification_plan(
            migration_paths=migration_paths,
        )
        inventory = build_iros_object_inventory(migration_paths=migration_paths)
    except ValueError as error:
        raise HostedVerificationContractError("migration_contract_invalid") from error
    declared_objects = frozenset(inventory.entries_by_name)
    required_targets = {
        *plan.target_objects,
        *_MUTATION_TARGETS.values(),
        "iros_readiness_gate_results",
        "iros_read_raw_provider_payload",
        "iros_run_hosted_negative_probe",
    }
    missing_required_targets = tuple(sorted(required_targets - declared_objects))
    if missing_required_targets:
        raise HostedVerificationContractError(
            "dispatch_target_absent",
        )
    try:
        constraint_index = build_iros_constraint_index(migration_paths=migration_paths)
        dispatches = _default_dispatches(plan, constraint_index)
    except ValueError as error:
        raise HostedVerificationContractError("constraint_binding_invalid") from error
    unreachable_mutations = tuple(
        dispatch.probe_id
        for dispatch in dispatches
        if dispatch.operation
        in {
            "attempt_duplicate_insert",
            "attempt_invalid_insert",
            "attempt_update",
        }
        and ("update" if dispatch.operation == "attempt_update" else "insert")
        not in inventory.entries_by_name[
            dispatch.target_objects[0]
        ].authenticated_privileges
        and not (
            dispatch.privileged_rpc is not None
            and dispatch.probe_id in _RUNNABLE_PRIVILEGED_PROBE_IDS
            and "execute"
            in inventory.entries_by_name[
                dispatch.privileged_rpc
            ].service_role_privileges
            and {"select", "update"}
            <= set(
                inventory.entries_by_name[
                    dispatch.target_objects[0]
                ].service_role_privileges
            )
        )
    )
    if unreachable_mutations:
        raise HostedVerificationContractError(
            "mutation_path_unreachable",
            blocking_probe_ids=unreachable_mutations,
        )
    return HostedVerificationExecutionContract.freeze(
        plan=plan,
        dispatches=dispatches,
        fixtures=_default_fixtures(),
        inventory_sha256=inventory.content_sha256,
        constraint_index_sha256=constraint_index.content_sha256,
    )


__all__ = [
    "HostedProbeDispatch",
    "HostedProbeFixture",
    "HostedVerificationExecutionAuthorization",
    "HostedVerificationExecutionContract",
    "HostedVerificationContractError",
    "build_default_iros_hosted_execution_contract",
]
