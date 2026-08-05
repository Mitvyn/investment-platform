from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping, Protocol
from urllib.parse import urlencode
import uuid

from investment_research_os.readiness_and_theses import (
    ReadinessAndThesisResult,
    ReadinessBlockingReason,
    ReadinessCheck,
    ReadinessGateResult,
    RequiredNextEvidence,
    ThesisChain,
    ThesisContent,
    ThesisCreationResult,
    ThesisVersion,
)
from investment_research_os.research_runs import (
    PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
    PERSONAL_RESEARCH_THESIS_CONTRACT_ID,
    PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
    QUESTION_TYPE_VERSION,
    THESIS_CONTRACT_ID,
    WORKFLOW_CONFIG_VERSION,
)
from workers.sec.storage import (
    JsonTransport,
    SupabaseStorageSettings,
    UrllibJsonTransport,
)


RECEIPT_FIELDS = {
    "operator_id",
    "research_run_id",
    "readiness_gate_result_id",
    "thesis_creation_result_id",
    "thesis_version_id",
    "creation_outcome",
    "reused",
}
CREATION_OUTCOMES = {
    "canonical_created",
    "provisional_created",
    "no_thesis",
}
READINESS_ROW_FIELDS = {
    "operator_id",
    "research_run_id",
    "committee_result_id",
    "committee_memo_id",
    "canonical_readiness",
}
CREATION_ROW_FIELDS = {
    "operator_id",
    "research_run_id",
    "readiness_gate_result_id",
    "creation_outcome",
    "thesis_version_id",
    "canonical_creation_result",
}
THESIS_ROW_FIELDS = {
    "operator_id",
    "id",
    "canonical_thesis",
}
CHAIN_ROW_FIELDS = {
    "operator_id",
    "security_id",
    "thesis_contract_id",
    "canonical_chain",
}
READINESS_FIELDS = {
    "contract_version",
    "readiness_gate_result_id",
    "operator_id",
    "security_id",
    "thesis_contract_id",
    "research_run_id",
    "evidence_bundle_id",
    "evidence_bundle_hash",
    "validated_grader_opinion_ids",
    "committee_result_id",
    "committee_memo_id",
    "committee_status",
    "requested_disposition",
    "final_disposition",
    "readiness_status",
    "gate_policy_version",
    "passed_checks",
    "failed_checks",
    "blocking_reasons",
    "required_next_evidence",
    "evaluated_at",
}
READINESS_CHECK_FIELDS = {
    "check_id",
    "check_version",
    "reason_code",
    "explanation",
    "reference_ids",
}
BLOCKING_REASON_FIELDS = {
    "reason_code",
    "check_id",
    "explanation",
}
NEXT_EVIDENCE_FIELDS = {
    "requirement_id",
    "description",
    "affected_check_ids",
}
CREATION_FIELDS = {
    "contract_version",
    "thesis_creation_result_id",
    "operator_id",
    "security_id",
    "thesis_contract_id",
    "research_run_id",
    "committee_result_id",
    "readiness_gate_result_id",
    "committee_status",
    "creation_outcome",
    "thesis_version_id",
    "reason_code",
    "created_at",
}
THESIS_FIELDS = {
    "contract_version",
    "thesis_version_id",
    "thesis_status",
    "operator_id",
    "security_id",
    "thesis_contract_id",
    "previous_canonical_thesis_version_id",
    "based_on_thesis_version_id",
    "research_run_id",
    "evidence_bundle_id",
    "evidence_bundle_hash",
    "question_type_version",
    "workflow_config_version",
    "proposition_id",
    "proposition_version",
    "validated_grader_opinion_ids",
    "committee_result_id",
    "committee_memo_id",
    "committee_status",
    "readiness_gate_result_id",
    "readiness_gate_policy_version",
    "requested_disposition",
    "final_disposition",
    "content",
    "created_at",
}
THESIS_CONTENT_FIELDS = {
    "core_thesis_statement_ids",
    "unresolved_disagreement_ids",
    "invalidation_statement_ids",
    "evidence_gap_statement_ids",
    "review_trigger_statement_id",
}
CHAIN_FIELDS = {
    "contract_version",
    "operator_id",
    "security_id",
    "thesis_contract_id",
    "active_canonical_thesis_version_id",
    "canonical_versions",
    "provisional_branches",
    "generated_at",
}
THESIS_CONTRACT_IDENTITIES = {
    THESIS_CONTRACT_ID: (
        QUESTION_TYPE_VERSION,
        WORKFLOW_CONFIG_VERSION,
        "biotech-readiness.v1",
    ),
    PERSONAL_RESEARCH_THESIS_CONTRACT_ID: (
        PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
        PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
        "biotech-personal-readiness.v1",
    ),
}


class ReadinessThesisRuntimeStorageError(RuntimeError):
    """Raised when atomic readiness/thesis persistence cannot be trusted."""


@dataclass(frozen=True, slots=True)
class ReadinessThesisRuntimeReceipt:
    operator_id: str
    research_run_id: str
    readiness_gate_result_id: str
    thesis_creation_result_id: str
    thesis_version_id: str | None
    creation_outcome: str
    reused: bool


class SupabaseReadinessThesisRuntimeStore:
    """Persists one readiness result and thesis outcome through one RPC."""

    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)

    def persist(
        self,
        result: ReadinessAndThesisResult,
    ) -> ReadinessThesisRuntimeReceipt:
        readiness = result.readiness
        creation = result.thesis_creation
        thesis = result.thesis
        _validate_result_identity(result)
        response = self.transport.request_json(
            "POST",
            (
                f"{self.settings.url.rstrip('/')}/rest/v1/rpc/"
                "iros_persist_readiness_thesis_runtime"
            ),
            headers={
                "Content-Type": "application/json",
                "apikey": self.settings.secret_key,
            },
            payload={
                "p_operator_id": readiness.operator_id,
                "p_readiness": readiness.as_dict(),
                "p_thesis_creation": creation.as_dict(),
                "p_thesis": None if thesis is None else thesis.as_dict(),
            },
        )
        if not 200 <= response.status < 300:
            raise ReadinessThesisRuntimeStorageError(
                "readiness thesis runtime persistence failed"
            )
        receipt = _receipt(response.payload)
        expected_thesis_id = None if thesis is None else thesis.thesis_version_id
        if (
            receipt.operator_id != readiness.operator_id
            or receipt.research_run_id != readiness.research_run_id
            or receipt.readiness_gate_result_id != readiness.readiness_gate_result_id
            or receipt.thesis_creation_result_id != creation.thesis_creation_result_id
            or receipt.thesis_version_id != expected_thesis_id
            or receipt.creation_outcome != creation.creation_outcome
        ):
            raise ReadinessThesisRuntimeStorageError(
                "readiness thesis receipt does not match persisted result"
            )
        return receipt


class ReadinessThesisReadModel(Protocol):
    def get_for_run(
        self,
        operator_id: str,
        research_run_id: str,
    ) -> ReadinessAndThesisResult | None: ...

    def get_readiness_by_id(
        self,
        operator_id: str,
        readiness_gate_result_id: str,
    ) -> ReadinessGateResult | None: ...

    def get_thesis_by_id(
        self,
        operator_id: str,
        thesis_version_id: str,
    ) -> ThesisVersion | None: ...

    def get_chain(
        self,
        operator_id: str,
        security_id: str,
        thesis_contract_id: str,
    ) -> ThesisChain: ...


class SupabaseReadinessThesisReadModel:
    """Reconstructs only owner-scoped canonical readiness/thesis contracts."""

    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)

    def get_for_run(
        self,
        operator_id: str,
        research_run_id: str,
    ) -> ReadinessAndThesisResult | None:
        operator_id = _uuid_text(operator_id)
        research_run_id = _uuid_text(research_run_id)
        readiness = self._get_readiness(
            operator_id,
            {"research_run_id": f"eq.{research_run_id}"},
        )
        if readiness is None:
            return None
        creation = self._get_creation(
            operator_id,
            {"research_run_id": f"eq.{research_run_id}"},
        )
        if creation is None:
            raise ReadinessThesisRuntimeStorageError(
                "readiness result is missing thesis creation outcome"
            )
        thesis = (
            None
            if creation.thesis_version_id is None
            else self.get_thesis_by_id(
                operator_id,
                creation.thesis_version_id,
            )
        )
        if creation.thesis_version_id is not None and thesis is None:
            raise ReadinessThesisRuntimeStorageError(
                "thesis creation outcome is missing thesis version"
            )
        result = ReadinessAndThesisResult(
            readiness=readiness,
            thesis_creation=creation,
            thesis=thesis,
        )
        _validate_result_identity(result)
        return result

    def get_readiness_by_id(
        self,
        operator_id: str,
        readiness_gate_result_id: str,
    ) -> ReadinessGateResult | None:
        operator_id = _uuid_text(operator_id)
        return self._get_readiness(
            operator_id,
            {"id": f"eq.{_uuid_text(readiness_gate_result_id)}"},
        )

    def get_thesis_by_id(
        self,
        operator_id: str,
        thesis_version_id: str,
    ) -> ThesisVersion | None:
        operator_id = _uuid_text(operator_id)
        thesis_version_id = _uuid_text(thesis_version_id)
        rows = self._rows(
            "iros_thesis_versions",
            operator_id,
            {"id": f"eq.{thesis_version_id}"},
            THESIS_ROW_FIELDS,
            "thesis",
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise ReadinessThesisRuntimeStorageError(
                "thesis read returned invalid canonical state"
            )
        try:
            row = rows[0]
            canonical = _mapping(row["canonical_thesis"])
            thesis = _thesis(canonical)
            if (
                _uuid_text(row["operator_id"]) != operator_id
                or _uuid_text(row["id"]) != thesis_version_id
                or thesis.operator_id != operator_id
                or thesis.thesis_version_id != thesis_version_id
                or thesis.as_dict() != canonical
            ):
                raise ValueError("thesis canonical identity drift")
            return thesis
        except (KeyError, TypeError, ValueError) as error:
            raise ReadinessThesisRuntimeStorageError(
                "thesis read returned invalid canonical state"
            ) from error

    def get_chain(
        self,
        operator_id: str,
        security_id: str,
        thesis_contract_id: str,
    ) -> ThesisChain:
        operator_id = _uuid_text(operator_id)
        security_id = _uuid_text(security_id)
        rows = self._rows(
            "iros_v_thesis_chains",
            operator_id,
            {
                "security_id": f"eq.{security_id}",
                "thesis_contract_id": f"eq.{thesis_contract_id}",
            },
            CHAIN_ROW_FIELDS,
            "thesis chain",
        )
        if not rows:
            return ThesisChain(
                operator_id=operator_id,
                security_id=security_id,
                thesis_contract_id=thesis_contract_id,
                active_canonical_thesis_version_id=None,
                canonical_versions=(),
                provisional_branches=(),
                generated_at=datetime(1970, 1, 1, tzinfo=UTC),
            )
        if len(rows) != 1:
            raise ReadinessThesisRuntimeStorageError(
                "thesis chain read returned invalid canonical state"
            )
        try:
            row = rows[0]
            canonical = _mapping(row["canonical_chain"])
            chain = _chain(canonical)
            if (
                _uuid_text(row["operator_id"]) != operator_id
                or _uuid_text(row["security_id"]) != security_id
                or str(row["thesis_contract_id"]) != thesis_contract_id
                or chain.operator_id != operator_id
                or chain.security_id != security_id
                or chain.thesis_contract_id != thesis_contract_id
                or chain.as_dict() != canonical
            ):
                raise ValueError("thesis chain canonical identity drift")
            _validate_chain(chain)
            return chain
        except (KeyError, TypeError, ValueError) as error:
            raise ReadinessThesisRuntimeStorageError(
                "thesis chain read returned invalid canonical state"
            ) from error

    def _get_readiness(
        self,
        operator_id: str,
        filters: Mapping[str, str],
    ) -> ReadinessGateResult | None:
        rows = self._rows(
            "iros_readiness_gate_results",
            operator_id,
            {**filters, "persistence_state": "eq.complete"},
            READINESS_ROW_FIELDS,
            "readiness",
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise ReadinessThesisRuntimeStorageError(
                "readiness read returned invalid canonical state"
            )
        try:
            row = rows[0]
            canonical = _mapping(row["canonical_readiness"])
            readiness = _readiness(canonical)
            if (
                _uuid_text(row["operator_id"]) != operator_id
                or readiness.operator_id != operator_id
                or _uuid_text(row["research_run_id"]) != readiness.research_run_id
                or _uuid_text(row["committee_result_id"])
                != readiness.committee_result_id
                or _uuid_text(row["committee_memo_id"]) != readiness.committee_memo_id
                or readiness.as_dict() != canonical
            ):
                raise ValueError("readiness canonical identity drift")
            return readiness
        except (KeyError, TypeError, ValueError) as error:
            raise ReadinessThesisRuntimeStorageError(
                "readiness read returned invalid canonical state"
            ) from error

    def _get_creation(
        self,
        operator_id: str,
        filters: Mapping[str, str],
    ) -> ThesisCreationResult | None:
        rows = self._rows(
            "iros_thesis_creation_results",
            operator_id,
            filters,
            CREATION_ROW_FIELDS,
            "thesis creation",
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise ReadinessThesisRuntimeStorageError(
                "thesis creation read returned invalid canonical state"
            )
        try:
            row = rows[0]
            canonical = _mapping(row["canonical_creation_result"])
            creation = _creation(canonical)
            row_thesis_id = row["thesis_version_id"]
            if (
                _uuid_text(row["operator_id"]) != operator_id
                or creation.operator_id != operator_id
                or _uuid_text(row["research_run_id"]) != creation.research_run_id
                or _uuid_text(row["readiness_gate_result_id"])
                != creation.readiness_gate_result_id
                or str(row["creation_outcome"]) != creation.creation_outcome
                or (None if row_thesis_id is None else _uuid_text(row_thesis_id))
                != creation.thesis_version_id
                or creation.as_dict() != canonical
            ):
                raise ValueError("thesis creation canonical identity drift")
            return creation
        except (KeyError, TypeError, ValueError) as error:
            raise ReadinessThesisRuntimeStorageError(
                "thesis creation read returned invalid canonical state"
            ) from error

    def _rows(
        self,
        resource: str,
        operator_id: str,
        filters: Mapping[str, str],
        fields: set[str],
        label: str,
    ) -> list[Mapping[str, Any]]:
        query = urlencode(
            {
                "operator_id": f"eq.{operator_id}",
                **filters,
                "select": ",".join(sorted(fields)),
            }
        )
        response = self.transport.request_json(
            "GET",
            f"{self.settings.url.rstrip('/')}/rest/v1/{resource}?{query}",
            headers={"apikey": self.settings.secret_key},
        )
        if (
            response.status != 200
            or not isinstance(response.payload, list)
            or any(
                not isinstance(item, Mapping) or set(item) != fields
                for item in response.payload
            )
        ):
            raise ReadinessThesisRuntimeStorageError(
                f"{label} read returned invalid canonical state"
            )
        return response.payload


class SupabaseReadinessAndThesisRepository:
    """Persists atomically, then trusts only exact reloaded domain state."""

    def __init__(
        self,
        *,
        runtime_store: SupabaseReadinessThesisRuntimeStore,
        read_model: ReadinessThesisReadModel,
    ) -> None:
        self._runtime_store = runtime_store
        self._read_model = read_model

    def get_for_run(
        self,
        operator_id: str,
        research_run_id: str,
    ) -> ReadinessAndThesisResult | None:
        return self._read_model.get_for_run(operator_id, research_run_id)

    def get_readiness_by_id(
        self,
        operator_id: str,
        readiness_gate_result_id: str,
    ) -> ReadinessGateResult | None:
        return self._read_model.get_readiness_by_id(
            operator_id,
            readiness_gate_result_id,
        )

    def get_thesis_by_id(
        self,
        operator_id: str,
        thesis_version_id: str,
    ) -> ThesisVersion | None:
        return self._read_model.get_thesis_by_id(
            operator_id,
            thesis_version_id,
        )

    def get_chain(
        self,
        operator_id: str,
        security_id: str,
        thesis_contract_id: str,
    ) -> ThesisChain:
        return self._read_model.get_chain(
            operator_id,
            security_id,
            thesis_contract_id,
        )

    def save(
        self,
        result: ReadinessAndThesisResult,
    ) -> ReadinessAndThesisResult:
        self._runtime_store.persist(result)
        persisted = self._read_model.get_for_run(
            result.readiness.operator_id,
            result.readiness.research_run_id,
        )
        if persisted is None:
            raise ReadinessThesisRuntimeStorageError(
                "reloaded readiness thesis result is unavailable"
            )
        if persisted != result:
            raise ReadinessThesisRuntimeStorageError(
                "reloaded readiness thesis result does not match"
            )
        return persisted


def _validate_result_identity(result: ReadinessAndThesisResult) -> None:
    readiness = result.readiness
    creation = result.thesis_creation
    thesis = result.thesis
    for value in (
        readiness.operator_id,
        readiness.research_run_id,
        readiness.readiness_gate_result_id,
        creation.thesis_creation_result_id,
    ):
        _uuid_text(value)
    if (
        creation.operator_id != readiness.operator_id
        or creation.security_id != readiness.security_id
        or creation.thesis_contract_id != readiness.thesis_contract_id
        or creation.research_run_id != readiness.research_run_id
        or creation.committee_result_id != readiness.committee_result_id
        or creation.readiness_gate_result_id != readiness.readiness_gate_result_id
        or creation.committee_status != readiness.committee_status
        or creation.creation_outcome not in CREATION_OUTCOMES
    ):
        raise ReadinessThesisRuntimeStorageError(
            "readiness thesis result identity is invalid"
        )
    if thesis is None:
        if (
            creation.creation_outcome != "no_thesis"
            or creation.thesis_version_id is not None
        ):
            raise ReadinessThesisRuntimeStorageError(
                "readiness thesis result identity is invalid"
            )
        return
    _uuid_text(thesis.thesis_version_id)
    if (
        creation.creation_outcome == "no_thesis"
        or creation.thesis_version_id != thesis.thesis_version_id
        or thesis.operator_id != readiness.operator_id
        or thesis.security_id != readiness.security_id
        or thesis.thesis_contract_id != readiness.thesis_contract_id
        or thesis.research_run_id != readiness.research_run_id
        or thesis.committee_result_id != readiness.committee_result_id
        or thesis.readiness_gate_result_id != readiness.readiness_gate_result_id
        or thesis.committee_status != readiness.committee_status
        or thesis.final_disposition != readiness.final_disposition
    ):
        raise ReadinessThesisRuntimeStorageError(
            "readiness thesis result identity is invalid"
        )


def _readiness(canonical: Mapping[str, Any]) -> ReadinessGateResult:
    if (
        set(canonical) != READINESS_FIELDS
        or canonical["contract_version"] != "readiness_gate_result.v1"
    ):
        raise ValueError("readiness canonical fields invalid")
    passed = _checks(canonical["passed_checks"])
    failed = _checks(canonical["failed_checks"])
    if (
        len(passed) + len(failed) != 11
        or len({item.check_id for item in (*passed, *failed)}) != 11
    ):
        raise ValueError("readiness check set invalid")
    result = ReadinessGateResult(
        readiness_gate_result_id=_uuid_text(canonical["readiness_gate_result_id"]),
        operator_id=_uuid_text(canonical["operator_id"]),
        security_id=_uuid_text(canonical["security_id"]),
        thesis_contract_id=str(canonical["thesis_contract_id"]),
        research_run_id=_uuid_text(canonical["research_run_id"]),
        evidence_bundle_id=_uuid_text(canonical["evidence_bundle_id"]),
        evidence_bundle_hash=_sha256(canonical["evidence_bundle_hash"]),
        validated_grader_opinion_ids=_uuid_tuple(
            canonical["validated_grader_opinion_ids"]
        ),
        committee_result_id=_uuid_text(canonical["committee_result_id"]),
        committee_memo_id=_uuid_text(canonical["committee_memo_id"]),
        committee_status=str(canonical["committee_status"]),
        requested_disposition=str(canonical["requested_disposition"]),
        final_disposition=str(canonical["final_disposition"]),
        readiness_status=str(canonical["readiness_status"]),
        gate_policy_version=str(canonical["gate_policy_version"]),
        passed_checks=passed,
        failed_checks=failed,
        blocking_reasons=_blocking_reasons(canonical["blocking_reasons"]),
        required_next_evidence=_next_evidence(canonical["required_next_evidence"]),
        evaluated_at=_timestamp(canonical["evaluated_at"]),
    )
    identity = THESIS_CONTRACT_IDENTITIES.get(result.thesis_contract_id)
    if (
        identity is None
        or result.committee_status
        not in {
            "complete",
            "complete_with_abstentions",
            "incomplete_required_grader_failed",
            "insufficient_accepted_opinions",
        }
        or result.requested_disposition
        not in {"reject", "monitor", "deep_research", "decision_ready"}
        or result.final_disposition
        not in {"reject", "monitor", "deep_research", "decision_ready"}
        or result.readiness_status not in {"passed", "blocked", "not_requested"}
        or result.gate_policy_version != identity[2]
    ):
        raise ValueError("readiness canonical values invalid")
    return result


def _checks(value: object) -> tuple[ReadinessCheck, ...]:
    items = _list_of_mappings(value)
    results = []
    for item in items:
        if set(item) != READINESS_CHECK_FIELDS:
            raise ValueError("readiness check fields invalid")
        results.append(
            ReadinessCheck(
                check_id=str(item["check_id"]),
                check_version=str(item["check_version"]),
                reason_code=str(item["reason_code"]),
                explanation=str(item["explanation"]),
                reference_ids=_string_tuple(item["reference_ids"]),
            )
        )
    return tuple(results)


def _blocking_reasons(
    value: object,
) -> tuple[ReadinessBlockingReason, ...]:
    items = _list_of_mappings(value)
    results = []
    for item in items:
        if set(item) != BLOCKING_REASON_FIELDS:
            raise ValueError("blocking reason fields invalid")
        results.append(
            ReadinessBlockingReason(
                reason_code=str(item["reason_code"]),
                check_id=str(item["check_id"]),
                explanation=str(item["explanation"]),
            )
        )
    return tuple(results)


def _next_evidence(value: object) -> tuple[RequiredNextEvidence, ...]:
    items = _list_of_mappings(value)
    results = []
    for item in items:
        if set(item) != NEXT_EVIDENCE_FIELDS:
            raise ValueError("next evidence fields invalid")
        results.append(
            RequiredNextEvidence(
                requirement_id=str(item["requirement_id"]),
                description=str(item["description"]),
                affected_check_ids=_string_tuple(item["affected_check_ids"]),
            )
        )
    return tuple(results)


def _creation(canonical: Mapping[str, Any]) -> ThesisCreationResult:
    if (
        set(canonical) != CREATION_FIELDS
        or canonical["contract_version"] != "thesis_creation_result.v1"
    ):
        raise ValueError("thesis creation canonical fields invalid")
    thesis_id = canonical["thesis_version_id"]
    result = ThesisCreationResult(
        thesis_creation_result_id=_uuid_text(canonical["thesis_creation_result_id"]),
        operator_id=_uuid_text(canonical["operator_id"]),
        security_id=_uuid_text(canonical["security_id"]),
        thesis_contract_id=str(canonical["thesis_contract_id"]),
        research_run_id=_uuid_text(canonical["research_run_id"]),
        committee_result_id=_uuid_text(canonical["committee_result_id"]),
        readiness_gate_result_id=_uuid_text(canonical["readiness_gate_result_id"]),
        committee_status=str(canonical["committee_status"]),
        creation_outcome=str(canonical["creation_outcome"]),
        thesis_version_id=(None if thesis_id is None else _uuid_text(thesis_id)),
        reason_code=str(canonical["reason_code"]),
        created_at=_timestamp(canonical["created_at"]),
    )
    if (
        result.thesis_contract_id not in THESIS_CONTRACT_IDENTITIES
        or result.creation_outcome not in CREATION_OUTCOMES
        or (result.creation_outcome == "no_thesis")
        != (result.thesis_version_id is None)
    ):
        raise ValueError("thesis creation canonical values invalid")
    return result


def _thesis(canonical: Mapping[str, Any]) -> ThesisVersion:
    if (
        set(canonical) != THESIS_FIELDS
        or canonical["contract_version"] != "thesis_version.v1"
    ):
        raise ValueError("thesis canonical fields invalid")
    previous = canonical["previous_canonical_thesis_version_id"]
    basis = canonical["based_on_thesis_version_id"]
    content = _mapping(canonical["content"])
    if set(content) != THESIS_CONTENT_FIELDS:
        raise ValueError("thesis content fields invalid")
    result = ThesisVersion(
        thesis_version_id=_uuid_text(canonical["thesis_version_id"]),
        thesis_status=str(canonical["thesis_status"]),
        operator_id=_uuid_text(canonical["operator_id"]),
        security_id=_uuid_text(canonical["security_id"]),
        thesis_contract_id=str(canonical["thesis_contract_id"]),
        previous_canonical_thesis_version_id=(
            None if previous is None else _uuid_text(previous)
        ),
        based_on_thesis_version_id=(None if basis is None else _uuid_text(basis)),
        research_run_id=_uuid_text(canonical["research_run_id"]),
        evidence_bundle_id=_uuid_text(canonical["evidence_bundle_id"]),
        evidence_bundle_hash=_sha256(canonical["evidence_bundle_hash"]),
        question_type_version=str(canonical["question_type_version"]),
        workflow_config_version=str(canonical["workflow_config_version"]),
        proposition_id=str(canonical["proposition_id"]),
        proposition_version=str(canonical["proposition_version"]),
        validated_grader_opinion_ids=_uuid_tuple(
            canonical["validated_grader_opinion_ids"]
        ),
        committee_result_id=_uuid_text(canonical["committee_result_id"]),
        committee_memo_id=_uuid_text(canonical["committee_memo_id"]),
        committee_status=str(canonical["committee_status"]),
        readiness_gate_result_id=_uuid_text(canonical["readiness_gate_result_id"]),
        readiness_gate_policy_version=str(canonical["readiness_gate_policy_version"]),
        requested_disposition=str(canonical["requested_disposition"]),
        final_disposition=str(canonical["final_disposition"]),
        content=ThesisContent(
            core_thesis_statement_ids=_string_tuple(
                content["core_thesis_statement_ids"]
            ),
            unresolved_disagreement_ids=_string_tuple(
                content["unresolved_disagreement_ids"]
            ),
            invalidation_statement_ids=_string_tuple(
                content["invalidation_statement_ids"]
            ),
            evidence_gap_statement_ids=_string_tuple(
                content["evidence_gap_statement_ids"]
            ),
            review_trigger_statement_id=str(content["review_trigger_statement_id"]),
        ),
        created_at=_timestamp(canonical["created_at"]),
    )
    identity = THESIS_CONTRACT_IDENTITIES.get(result.thesis_contract_id)
    if (
        result.thesis_status not in {"canonical", "provisional"}
        or identity is None
        or result.question_type_version != identity[0]
        or result.workflow_config_version != identity[1]
        or result.committee_status not in {"complete", "complete_with_abstentions"}
        or result.readiness_gate_policy_version != identity[2]
        or not result.content.core_thesis_statement_ids
        or not result.content.invalidation_statement_ids
        or not result.content.review_trigger_statement_id
    ):
        raise ValueError("thesis canonical values invalid")
    return result


def _chain(canonical: Mapping[str, Any]) -> ThesisChain:
    if (
        set(canonical) != CHAIN_FIELDS
        or canonical["contract_version"] != "thesis_chain.v1"
    ):
        raise ValueError("thesis chain canonical fields invalid")
    active = canonical["active_canonical_thesis_version_id"]
    return ThesisChain(
        operator_id=_uuid_text(canonical["operator_id"]),
        security_id=_uuid_text(canonical["security_id"]),
        thesis_contract_id=str(canonical["thesis_contract_id"]),
        active_canonical_thesis_version_id=(
            None if active is None else _uuid_text(active)
        ),
        canonical_versions=tuple(
            _thesis(item) for item in _list_of_mappings(canonical["canonical_versions"])
        ),
        provisional_branches=tuple(
            _thesis(item)
            for item in _list_of_mappings(canonical["provisional_branches"])
        ),
        generated_at=_timestamp(canonical["generated_at"]),
    )


def _validate_chain(chain: ThesisChain) -> None:
    versions = (*chain.canonical_versions, *chain.provisional_branches)
    expected_previous = None
    canonical_ids: set[str] = set()
    canonical_order_valid = True
    for thesis in chain.canonical_versions:
        if (
            thesis.previous_canonical_thesis_version_id != expected_previous
            or thesis.based_on_thesis_version_id != expected_previous
        ):
            canonical_order_valid = False
        expected_previous = thesis.thesis_version_id
        canonical_ids.add(thesis.thesis_version_id)
    if (
        chain.thesis_contract_id not in THESIS_CONTRACT_IDENTITIES
        or any(
            thesis.operator_id != chain.operator_id
            or thesis.security_id != chain.security_id
            or thesis.thesis_contract_id != chain.thesis_contract_id
            for thesis in versions
        )
        or any(
            thesis.thesis_status != "canonical" for thesis in chain.canonical_versions
        )
        or any(
            thesis.thesis_status != "provisional"
            for thesis in chain.provisional_branches
        )
        or len({thesis.thesis_version_id for thesis in versions}) != len(versions)
        or not canonical_order_valid
        or any(
            thesis.based_on_thesis_version_id is not None
            and thesis.based_on_thesis_version_id not in canonical_ids
            for thesis in chain.provisional_branches
        )
        or any(thesis.created_at > chain.generated_at for thesis in versions)
        or chain.active_canonical_thesis_version_id
        != (
            None
            if not chain.canonical_versions
            else chain.canonical_versions[-1].thesis_version_id
        )
    ):
        raise ValueError("thesis chain canonical values invalid")


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("canonical value must be an object")
    return value


def _list_of_mappings(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise TypeError("canonical value must be an object array")
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TypeError("canonical value must be a string array")
    return tuple(value)


def _uuid_tuple(value: object) -> tuple[str, ...]:
    return tuple(_uuid_text(item) for item in _string_tuple(value))


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("timestamp must be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def _sha256(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("value must be lowercase sha256")
    return value


def _receipt(payload: object) -> ReadinessThesisRuntimeReceipt:
    if (
        not isinstance(payload, list)
        or len(payload) != 1
        or not isinstance(payload[0], Mapping)
        or set(payload[0]) != RECEIPT_FIELDS
    ):
        raise ReadinessThesisRuntimeStorageError(
            "readiness thesis receipt is malformed"
        )
    row = payload[0]
    try:
        thesis_id = row["thesis_version_id"]
        receipt = ReadinessThesisRuntimeReceipt(
            operator_id=_uuid_text(row["operator_id"]),
            research_run_id=_uuid_text(row["research_run_id"]),
            readiness_gate_result_id=_uuid_text(row["readiness_gate_result_id"]),
            thesis_creation_result_id=_uuid_text(row["thesis_creation_result_id"]),
            thesis_version_id=(None if thesis_id is None else _uuid_text(thesis_id)),
            creation_outcome=str(row["creation_outcome"]),
            reused=row["reused"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ReadinessThesisRuntimeStorageError(
            "readiness thesis receipt is malformed"
        ) from error
    if (
        receipt.creation_outcome not in CREATION_OUTCOMES
        or not isinstance(receipt.reused, bool)
        or (
            receipt.creation_outcome == "no_thesis"
            and receipt.thesis_version_id is not None
        )
        or (
            receipt.creation_outcome != "no_thesis"
            and receipt.thesis_version_id is None
        )
    ):
        raise ReadinessThesisRuntimeStorageError(
            "readiness thesis receipt is malformed"
        )
    return receipt


def _uuid_text(value: object) -> str:
    return str(uuid.UUID(str(value)))


__all__ = [
    "ReadinessThesisReadModel",
    "ReadinessThesisRuntimeReceipt",
    "ReadinessThesisRuntimeStorageError",
    "SupabaseReadinessAndThesisRepository",
    "SupabaseReadinessThesisReadModel",
    "SupabaseReadinessThesisRuntimeStore",
]
