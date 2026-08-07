from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

from investment_research_os.hosted_verification import (
    HostedVerificationAuthorization,
    HostedVerificationPlan,
)


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
        if (
            not target_objects
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
    target_manifest_sha256: str
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
        fixtures_by_id = {item.fixture_id: item for item in ordered_fixtures}
        if any(
            item.operation in {"attempt_insert", "attempt_update"}
            and fixtures_by_id[item.fixture_id].cleanup_rule != "transaction_rollback"
            for item in ordered_dispatches
        ):
            raise ValueError(
                "hosted verification v3 mutating fixture cleanup is invalid"
            )
        if any(
            not set(item.target_objects) <= set(plan.target_objects)
            for item in ordered_dispatches
        ):
            raise ValueError("hosted verification v3 dispatch target is outside plan")
        dispatch_hash = _sha256([item.content_sha256 for item in ordered_dispatches])
        fixture_hash = _sha256([item.content_sha256 for item in ordered_fixtures])
        version = "hosted-verification-execution-contract.v3"
        content = {
            "contract_version": version,
            "plan_sha256": plan.content_sha256,
            "migration_manifest_sha256": plan.migration_manifest_sha256,
            "target_manifest_sha256": plan.target_manifest_sha256,
            "dispatch_registry_sha256": dispatch_hash,
            "fixture_set_sha256": fixture_hash,
            "required_scopes": list(plan.required_scopes),
        }
        return cls(
            contract_version=version,
            plan_sha256=plan.content_sha256,
            migration_manifest_sha256=plan.migration_manifest_sha256,
            target_manifest_sha256=plan.target_manifest_sha256,
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
        ):
            return False
        return self.content_sha256 == _sha256(
            {
                "contract_version": self.contract_version,
                "plan_sha256": self.plan_sha256,
                "migration_manifest_sha256": self.migration_manifest_sha256,
                "target_manifest_sha256": self.target_manifest_sha256,
                "dispatch_registry_sha256": self.dispatch_registry_sha256,
                "fixture_set_sha256": self.fixture_set_sha256,
                "required_scopes": list(self.required_scopes),
            }
        )


@dataclass(frozen=True, slots=True)
class HostedVerificationExecutionAuthorization:
    contract_version: str
    authorization_sha256: str
    plan_sha256: str
    migration_manifest_sha256: str
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
            "target_manifest_sha256": execution_contract.target_manifest_sha256,
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
                "target_manifest_sha256": self.target_manifest_sha256,
                "dispatch_registry_sha256": self.dispatch_registry_sha256,
                "fixture_set_sha256": self.fixture_set_sha256,
            }
        )


__all__ = [
    "HostedProbeDispatch",
    "HostedProbeFixture",
    "HostedVerificationExecutionAuthorization",
    "HostedVerificationExecutionContract",
]
