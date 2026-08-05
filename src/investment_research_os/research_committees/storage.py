from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

from investment_research_os.grader_executions import (
    AbstentionResult,
    ContradictingEvidence,
    EvidenceGap,
    GraderOpinion,
    MaterialClaim,
)
from investment_research_os.ids import stable_id
from investment_research_os.research_runs import QUESTION_TYPE, QUESTION_TYPE_VERSION
from workers.sec.storage import (
    EvidenceStorageError,
    JsonTransport,
    SupabaseStorageSettings,
    UrllibJsonTransport,
)

from . import (
    MVP_GRADER_ROSTER,
    CommitteeAccounting,
    CommitteeGraderResult,
    ResearchCommitteeResult,
)

COMMITTEE_ROW_FIELDS = {
    "operator_id",
    "research_run_id",
    "security_id",
    "evidence_bundle_id",
    "evidence_bundle_hash",
    "committee_result_id",
    "workflow_config_version",
    "proposition_id",
    "proposition_version",
    "rendered_proposition_text",
    "committee_status",
    "accounting",
    "stance_counts",
    "idempotency_key",
    "canonical_committee",
    "derived_at",
    "created_at",
}
GRADER_ROW_FIELDS = {
    "operator_id",
    "research_run_id",
    "committee_result_id",
    "grader_execution_id",
    "grader_opinion_id",
    "grader_id",
    "grader_version",
    "roster_position",
    "required",
    "execution_state",
    "owned_decision_question",
    "canonical_execution",
    "canonical_opinion",
    "not_eligible",
    "not_executed",
    "failure",
    "persisted_at",
}
COMMITTEE_FIELDS = {
    "contract_version",
    "research_run_id",
    "evidence_bundle_id",
    "evidence_bundle_hash",
    "workflow_config_version",
    "proposition_id",
    "proposition_version",
    "rendered_proposition_text",
    "committee_status",
    "accounting",
    "stance_counts",
    "stance_matrix",
    "grader_results",
    "derived_at",
}
GRADER_RESULT_FIELDS = {
    "contract_version",
    "grader_id",
    "grader_version",
    "grader_contract_version",
    "output_schema_version",
    "required",
    "evidence_bundle_id",
    "evidence_bundle_hash",
    "execution_id",
    "execution_state",
    "opinion",
    "not_eligible",
    "not_executed",
    "failure",
    "persisted_at",
}
COMMITTEE_OPINION_FIELDS = {
    "opinion_id",
    "owned_decision_question",
    "stance",
    "confidence",
    "summary",
    "material_claims",
    "assumptions",
    "contradicting_evidence",
    "evidence_gaps",
    "invalidation_signals",
    "proposition",
    "domain_payload",
    "abstention",
    "execution_metadata",
    "created_at",
}


@dataclass(frozen=True, slots=True)
class _PersistedExecution:
    execution_id: str
    prompt_version: str
    request: object
    attempts: tuple[None, ...]
    canonical: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return dict(self.canonical)


class ResearchCommitteeStorageError(EvidenceStorageError):
    """Raised when committee lifecycle persistence cannot be trusted."""


class SupabaseResearchCommitteeRepository:
    """Persists one immutable committee through draft, children, finalization."""

    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)
        self._read_model = SupabaseResearchCommitteeReadModel(
            settings,
            transport=self.transport,
        )

    def begin_committee(
        self,
        result: ResearchCommitteeResult,
    ) -> ResearchCommitteeResult:
        canonical = result.as_dict()
        self._insert(
            "iros_committee_results",
            "operator_id,idempotency_key",
            {
                "id": _uuid_text(result.committee_id),
                "operator_id": _uuid_text(result.operator_id),
                "research_run_id": _uuid_text(result.research_run_id),
                "security_id": _uuid_text(result.security_id),
                "evidence_bundle_id": _uuid_text(result.evidence_bundle_id),
                "evidence_bundle_hash": _sha256(result.evidence_bundle_hash),
                "workflow_config_version": result.workflow_config_version,
                "proposition_id": result.proposition_id,
                "proposition_version": result.proposition_version,
                "rendered_proposition_text": result.rendered_proposition_text,
                "committee_status": result.status,
                "accounting": canonical["accounting"],
                "stance_counts": canonical["stance_counts"],
                "idempotency_key": _sha256(result.committee_key),
                "canonical_committee": canonical,
                "derived_at": result.created_at.isoformat(),
                "persistence_state": "draft",
            },
        )
        return result

    def save_grader_state(
        self,
        committee: ResearchCommitteeResult,
        result: CommitteeGraderResult,
    ) -> CommitteeGraderResult:
        canonical = result.as_dict()
        self._insert(
            "iros_committee_grader_results",
            "operator_id,committee_result_id,grader_id",
            {
                "id": stable_id(
                    committee.operator_id,
                    "committee-grader-result",
                    f"{committee.committee_id}:{result.grader_id}",
                ),
                "operator_id": _uuid_text(committee.operator_id),
                "committee_result_id": _uuid_text(committee.committee_id),
                "workflow_config_version": committee.workflow_config_version,
                "grader_execution_id": canonical["execution_id"],
                "grader_opinion_id": (
                    None
                    if result.opinion is None
                    else _uuid_text(result.opinion.opinion_id)
                ),
                "grader_id": result.grader_id,
                "grader_version": result.grader_version,
                "roster_position": _roster_position(result.grader_id),
                "required": result.required,
                "execution_state": result.execution_state,
                "not_eligible": canonical["not_eligible"],
                "not_executed": canonical["not_executed"],
                "failure": canonical["failure"],
                "persisted_at": result.persisted_at.isoformat(),
            },
        )
        return result

    def finalize_committee(
        self,
        result: ResearchCommitteeResult,
    ) -> ResearchCommitteeResult:
        query = urlencode(
            {
                "id": f"eq.{_uuid_text(result.committee_id)}",
                "operator_id": f"eq.{_uuid_text(result.operator_id)}",
                "persistence_state": "eq.draft",
            }
        )
        response = self.transport.request_json(
            "PATCH",
            (f"{self.settings.url.rstrip('/')}/rest/v1/iros_committee_results?{query}"),
            headers={
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
                "apikey": self.settings.secret_key,
            },
            payload={"persistence_state": "complete"},
        )
        if response.status not in (200, 204):
            raise ResearchCommitteeStorageError(
                "committee store failed to finalize committee"
            )
        persisted = self._read_model.get_by_id(
            result.operator_id,
            result.committee_id,
        )
        if (
            persisted is None
            or persisted.security_id != result.security_id
            or persisted.committee_key != result.committee_key
            or persisted.as_dict() != result.as_dict()
        ):
            raise ResearchCommitteeStorageError(
                "persisted committee does not match finalization"
            )
        return persisted

    def get(
        self,
        operator_id: str,
        committee_key: str,
    ) -> ResearchCommitteeResult | None:
        return self._read_model.get_for_key(operator_id, committee_key)

    def get_by_id(
        self,
        operator_id: str,
        committee_id: str,
    ) -> ResearchCommitteeResult | None:
        return self._read_model.get_by_id(operator_id, committee_id)

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
            raise ResearchCommitteeStorageError(
                f"committee store failed to persist {table}"
            )


class SupabaseResearchCommitteeReadModel:
    """Strictly reconstructs one completed owner-scoped committee."""

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
    ) -> ResearchCommitteeResult | None:
        return self._get_one(
            operator_id,
            {"research_run_id": f"eq.{_uuid_text(research_run_id)}"},
        )

    def get_for_key(
        self,
        operator_id: str,
        committee_key: str,
    ) -> ResearchCommitteeResult | None:
        return self._get_one(
            operator_id,
            {"idempotency_key": f"eq.{_sha256(committee_key)}"},
        )

    def get_by_id(
        self,
        operator_id: str,
        committee_id: str,
    ) -> ResearchCommitteeResult | None:
        return self._get_one(
            operator_id,
            {"id": f"eq.{_uuid_text(committee_id)}"},
        )

    def _get_one(
        self,
        operator_id: str,
        filters: Mapping[str, str],
    ) -> ResearchCommitteeResult | None:
        operator_id = _uuid_text(operator_id)
        query = urlencode(
            {
                "operator_id": f"eq.{operator_id}",
                "persistence_state": "eq.complete",
                **filters,
                "select": ",".join(
                    "committee_result_id:id"
                    if field == "committee_result_id"
                    else field
                    for field in sorted(COMMITTEE_ROW_FIELDS)
                ),
            }
        )
        response = self.transport.request_json(
            "GET",
            (f"{self.settings.url.rstrip('/')}/rest/v1/iros_committee_results?{query}"),
            headers={"apikey": self.settings.secret_key},
        )
        rows = _rows(response.status, response.payload, "committee")
        if not rows:
            return None
        if len(rows) != 1 or set(rows[0]) != COMMITTEE_ROW_FIELDS:
            raise EvidenceStorageError(
                "committee store returned duplicate or malformed rows"
            )
        row = rows[0]
        committee_id = _uuid_text(row["committee_result_id"])
        grader_query = urlencode(
            {
                "operator_id": f"eq.{operator_id}",
                "committee_result_id": f"eq.{committee_id}",
                "select": ",".join(sorted(GRADER_ROW_FIELDS)),
                "order": "roster_position.asc",
            }
        )
        grader_response = self.transport.request_json(
            "GET",
            (
                f"{self.settings.url.rstrip('/')}/rest/v1/"
                f"iros_v_committee_grader_results?{grader_query}"
            ),
            headers={"apikey": self.settings.secret_key},
        )
        grader_rows = _rows(
            grader_response.status,
            grader_response.payload,
            "committee grader",
        )
        try:
            return _committee_from_rows(operator_id, row, grader_rows)
        except (KeyError, TypeError, ValueError) as error:
            raise EvidenceStorageError(
                "committee store returned invalid canonical state"
            ) from error


def _rows(status: int, payload: object, label: str) -> list[Mapping[str, Any]]:
    if status != 200 or not isinstance(payload, list):
        raise EvidenceStorageError(f"{label} store returned invalid payload")
    if any(not isinstance(item, Mapping) for item in payload):
        raise EvidenceStorageError(f"{label} store returned invalid payload")
    return payload


def _committee_from_rows(
    operator_id: str,
    row: Mapping[str, Any],
    grader_rows: list[Mapping[str, Any]],
) -> ResearchCommitteeResult:
    canonical = _mapping(row["canonical_committee"])
    if set(canonical) != COMMITTEE_FIELDS:
        raise ValueError("committee canonical fields invalid")
    committee_id = _uuid_text(row["committee_result_id"])
    research_run_id = _uuid_text(row["research_run_id"])
    evidence_bundle_id = _uuid_text(row["evidence_bundle_id"])
    security_id = _uuid_text(row["security_id"])
    if (
        _uuid_text(row["operator_id"]) != operator_id
        or canonical["contract_version"] != "committee_state.v1"
        or canonical["research_run_id"] != research_run_id
        or canonical["evidence_bundle_id"] != evidence_bundle_id
        or canonical["evidence_bundle_hash"] != row["evidence_bundle_hash"]
        or canonical["workflow_config_version"] != row["workflow_config_version"]
        or canonical["proposition_id"] != row["proposition_id"]
        or canonical["proposition_version"] != row["proposition_version"]
        or canonical["rendered_proposition_text"] != row["rendered_proposition_text"]
        or canonical["committee_status"] != row["committee_status"]
        or canonical["accounting"] != row["accounting"]
        or canonical["stance_counts"] != row["stance_counts"]
        or _timestamp(canonical["derived_at"]) != _timestamp(row["derived_at"])
    ):
        raise ValueError("committee canonical identity invalid")
    canonical_results = canonical["grader_results"]
    if not isinstance(canonical_results, list) or len(canonical_results) != 5:
        raise ValueError("committee grader results invalid")
    if len(grader_rows) != 5 or any(
        set(item) != GRADER_ROW_FIELDS for item in grader_rows
    ):
        raise ValueError("committee grader rows invalid")
    expected_roster = tuple(item.grader_id for item in MVP_GRADER_ROSTER)
    actual_roster = tuple(str(item["grader_id"]) for item in grader_rows)
    positions = tuple(item["roster_position"] for item in grader_rows)
    if actual_roster != expected_roster or positions != (1, 2, 3, 4, 5):
        raise ValueError("committee grader roster invalid")
    grader_results = tuple(
        _grader_result(
            operator_id=operator_id,
            committee_id=committee_id,
            research_run_id=research_run_id,
            evidence_bundle_id=evidence_bundle_id,
            evidence_bundle_hash=str(row["evidence_bundle_hash"]),
            workflow_config_version=str(row["workflow_config_version"]),
            row=grader_row,
            canonical=_mapping(canonical_result),
            definition=definition,
        )
        for grader_row, canonical_result, definition in zip(
            grader_rows,
            canonical_results,
            MVP_GRADER_ROSTER,
            strict=True,
        )
    )
    accounting = _accounting(canonical["accounting"], canonical["stance_counts"])
    if accounting != _derived_accounting(grader_results):
        raise ValueError("committee accounting disagrees with grader rows")
    result = ResearchCommitteeResult(
        committee_id=committee_id,
        committee_key=_sha256(row["idempotency_key"]),
        operator_id=operator_id,
        research_run_id=research_run_id,
        security_id=security_id,
        evidence_bundle_id=evidence_bundle_id,
        evidence_bundle_hash=_sha256(row["evidence_bundle_hash"]),
        question_type_id=QUESTION_TYPE,
        question_type_version=QUESTION_TYPE_VERSION,
        workflow_config_version=str(row["workflow_config_version"]),
        proposition_id=str(row["proposition_id"]),
        proposition_version=str(row["proposition_version"]),
        rendered_proposition_text=str(row["rendered_proposition_text"]),
        grader_results=grader_results,
        status=str(row["committee_status"]),
        accounting=accounting,
        created_at=_timestamp(row["derived_at"]),
    )
    if result.as_dict() != canonical:
        raise ValueError("committee canonical reconstruction mismatch")
    return result


def _grader_result(
    *,
    operator_id: str,
    committee_id: str,
    research_run_id: str,
    evidence_bundle_id: str,
    evidence_bundle_hash: str,
    workflow_config_version: str,
    row: Mapping[str, Any],
    canonical: Mapping[str, Any],
    definition,
) -> CommitteeGraderResult:
    if set(canonical) != GRADER_RESULT_FIELDS:
        raise ValueError("committee grader canonical fields invalid")
    state = str(row["execution_state"])
    if (
        _uuid_text(row["operator_id"]) != operator_id
        or _uuid_text(row["research_run_id"]) != research_run_id
        or _uuid_text(row["committee_result_id"]) != committee_id
        or row["grader_id"] != definition.grader_id
        or row["grader_version"] != definition.grader_version
        or row["owned_decision_question"] != definition.owned_decision_question
        or row["required"] is not definition.required_when_eligible
        or canonical["contract_version"] != "committee_grader_result.v1"
        or canonical["grader_id"] != row["grader_id"]
        or canonical["grader_version"] != row["grader_version"]
        or canonical["required"] != row["required"]
        or canonical["evidence_bundle_id"] != evidence_bundle_id
        or canonical["evidence_bundle_hash"] != evidence_bundle_hash
        or canonical["execution_state"] != state
        or canonical["not_eligible"] != row["not_eligible"]
        or canonical["not_executed"] != row["not_executed"]
        or canonical["failure"] != row["failure"]
        or _timestamp(canonical["persisted_at"]) != _timestamp(row["persisted_at"])
    ):
        raise ValueError("committee grader canonical identity invalid")
    execution = _execution(
        operator_id,
        row,
        canonical,
        workflow_config_version,
    )
    opinion = _opinion(row, canonical)
    if (opinion is None) != (state not in {"accepted", "abstained"}):
        raise ValueError("committee grader opinion state invalid")
    detail = row["not_eligible"] or row["not_executed"] or row["failure"] or {}
    eligibility_version = (
        str(detail.get("eligibility_rule_version"))
        if state == "not_eligible"
        else (
            ""
            if execution is None
            else str(execution.canonical["eligibility_rule_version"])
        )
    )
    reason_code = (
        None
        if not detail
        else str(detail.get("reason_code") or detail.get("final_reason"))
    )
    return CommitteeGraderResult(
        grader_id=definition.grader_id,
        grader_version=definition.grader_version,
        grader_contract_version=str(canonical["grader_contract_version"]),
        output_schema_version=str(canonical["output_schema_version"]),
        eligibility_rule_version=eligibility_version,
        owned_decision_question=definition.owned_decision_question,
        required=definition.required_when_eligible,
        eligible=state != "not_eligible",
        execution_state=state,
        evidence_bundle_id=evidence_bundle_id,
        evidence_bundle_hash=evidence_bundle_hash,
        opinion=opinion,
        execution=execution,  # type: ignore[arg-type]
        reason_code=reason_code,
        persisted_at=_timestamp(row["persisted_at"]),
    )


def _execution(
    operator_id: str,
    row: Mapping[str, Any],
    canonical: Mapping[str, Any],
    workflow_config_version: str,
) -> _PersistedExecution | None:
    state = str(row["execution_state"])
    raw = row["canonical_execution"]
    if state == "not_eligible":
        if raw is not None or row["grader_execution_id"] is not None:
            raise ValueError("not eligible execution invalid")
        return None
    execution = _mapping(raw)
    execution_id = _uuid_text(row["grader_execution_id"])
    if (
        execution.get("contract_version") != "grader_execution.v1"
        or execution.get("id") != execution_id
        or execution.get("operator_id") != operator_id
        or execution.get("research_run_id") != row["research_run_id"]
        or execution.get("evidence_bundle_id") != canonical["evidence_bundle_id"]
        or execution.get("evidence_bundle_hash") != canonical["evidence_bundle_hash"]
        or execution.get("question_type_id") != QUESTION_TYPE
        or execution.get("question_type_version") != QUESTION_TYPE_VERSION
        or execution.get("workflow_config_version") != workflow_config_version
        or execution.get("grader_id") != row["grader_id"]
        or execution.get("grader_version") != row["grader_version"]
        or execution.get("execution_state") != state
    ):
        raise ValueError("grader execution identity invalid")
    model = SimpleNamespace(
        config_id=str(execution["model_config_id"]),
        provider=str(execution["provider"]),
        model=str(execution["model"]),
    )
    attempt_count = (
        0
        if canonical["opinion"] is None
        else int(_mapping(canonical["opinion"])["execution_metadata"]["attempt_count"])
    )
    return _PersistedExecution(
        execution_id=execution_id,
        prompt_version=str(execution["prompt_version"]),
        request=SimpleNamespace(model=model),
        attempts=(None,) * attempt_count,
        canonical=execution,
    )


def _opinion(
    row: Mapping[str, Any],
    canonical: Mapping[str, Any],
) -> GraderOpinion | None:
    state = str(row["execution_state"])
    raw = canonical["opinion"]
    stored = row["canonical_opinion"]
    if state not in {"accepted", "abstained"}:
        if (
            raw is not None
            or stored is not None
            or row["grader_opinion_id"] is not None
        ):
            raise ValueError("grader opinion invalid")
        return None
    value = _mapping(raw)
    persisted = _mapping(stored)
    if set(value) != COMMITTEE_OPINION_FIELDS:
        raise ValueError("committee opinion fields invalid")
    proposition = _mapping(value["proposition"])
    payload_key = f"{row['grader_id']}_payload"
    if (
        value["opinion_id"] != _uuid_text(row["grader_opinion_id"])
        or persisted.get("opinion_id") != value["opinion_id"]
        or persisted.get("execution_id") != row["grader_execution_id"]
        or persisted.get("grader_id") != row["grader_id"]
        or persisted.get("grader_version") != row["grader_version"]
        or persisted.get("execution_state") != state
        or persisted.get("owned_decision_question") != value["owned_decision_question"]
        or persisted.get("stance") != value["stance"]
        or persisted.get("confidence") != value["confidence"]
        or persisted.get("summary") != value["summary"]
        or persisted.get("material_claims") != value["material_claims"]
        or persisted.get("assumptions") != value["assumptions"]
        or persisted.get("contradicting_evidence") != value["contradicting_evidence"]
        or persisted.get("evidence_gaps") != value["evidence_gaps"]
        or persisted.get("invalidation_signals") != value["invalidation_signals"]
        or persisted.get("proposition") != proposition
        or persisted.get(payload_key) != value["domain_payload"]
        or persisted.get("abstention") != value["abstention"]
    ):
        raise ValueError("grader opinion identity invalid")
    abstention = value["abstention"]
    return GraderOpinion(
        opinion_id=str(value["opinion_id"]),
        execution_state=state,
        grader_id=str(row["grader_id"]),
        grader_version=str(row["grader_version"]),
        owned_decision_question=str(value["owned_decision_question"]),
        proposition_id=str(proposition["proposition_id"]),
        proposition_version=str(proposition["proposition_version"]),
        rendered_proposition_text=str(proposition["rendered_proposition_text"]),
        grader_stance=(
            None
            if proposition["grader_stance"] is None
            else str(proposition["grader_stance"])
        ),
        stance_rationale=str(proposition["stance_rationale"] or ""),
        confidence=str(value["confidence"]),
        summary=str(value["summary"]),
        material_claims=tuple(
            MaterialClaim(
                claim_id=str(item["claim_id"]),
                claim=str(item["claim"]),
                materiality=str(item["materiality"]),
                evidence_ids=tuple(item["evidence_ids"]),
            )
            for item in _mapping_list(value["material_claims"])
        ),
        assumptions=tuple(value["assumptions"]),
        contradicting_evidence=tuple(
            ContradictingEvidence(
                evidence_id=str(item["evidence_id"]),
                explanation=str(item["explanation"]),
            )
            for item in _mapping_list(value["contradicting_evidence"])
        ),
        evidence_gaps=tuple(
            EvidenceGap(
                gap_id=str(item["gap_id"]),
                description=str(item["description"]),
                required_evidence=str(item["required_evidence"]),
            )
            for item in _mapping_list(value["evidence_gaps"])
        ),
        invalidation_signals=tuple(value["invalidation_signals"]),
        abstention=(
            None
            if abstention is None
            else AbstentionResult(
                reason_code=str(abstention["reason_code"]),
                reason=str(abstention["reason"]),
                missing_or_inadequate_evidence=tuple(
                    abstention["missing_or_inadequate_evidence"]
                ),
                evidence_required=tuple(abstention["evidence_required"]),
                confidence=str(abstention["confidence"]),
            )
        ),
        domain_payload=_mapping(value["domain_payload"]),
    )


def _accounting(accounting: object, stances: object) -> CommitteeAccounting:
    counts = _mapping(accounting)
    stance_counts = _mapping(stances)
    if set(counts) != {
        "eligible_count",
        "accepted_count",
        "abstained_count",
        "not_eligible_count",
        "failed_count",
        "not_executed_count",
    } or set(stance_counts) != {"supports", "mixed", "challenges"}:
        raise ValueError("committee accounting invalid")
    values = (*counts.values(), *stance_counts.values())
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("committee accounting invalid")
    return CommitteeAccounting(
        eligible_count=counts["eligible_count"],
        accepted_count=counts["accepted_count"],
        abstained_count=counts["abstained_count"],
        not_eligible_count=counts["not_eligible_count"],
        failed_count=counts["failed_count"],
        not_executed_count=counts["not_executed_count"],
        supports_count=stance_counts["supports"],
        mixed_count=stance_counts["mixed"],
        challenges_count=stance_counts["challenges"],
    )


def _derived_accounting(
    grader_results: tuple[CommitteeGraderResult, ...],
) -> CommitteeAccounting:
    states = tuple(item.execution_state for item in grader_results)
    stances = tuple(item.stance for item in grader_results if item.stance is not None)
    return CommitteeAccounting(
        eligible_count=sum(item.eligible for item in grader_results),
        accepted_count=states.count("accepted"),
        abstained_count=states.count("abstained"),
        not_eligible_count=states.count("not_eligible"),
        failed_count=states.count("failed"),
        not_executed_count=states.count("not_executed"),
        supports_count=stances.count("supports"),
        mixed_count=stances.count("mixed"),
        challenges_count=stances.count("challenges"),
    )


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("expected object")
    return value


def _mapping_list(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise TypeError("expected object list")
    return value


def _timestamp(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp timezone missing")
    return parsed


def _uuid_text(value: object) -> str:
    return str(uuid.UUID(str(value)))


def _roster_position(grader_id: str) -> int:
    for position, definition in enumerate(MVP_GRADER_ROSTER, start=1):
        if definition.grader_id == grader_id:
            return position
    raise ResearchCommitteeStorageError("committee grader is outside MVP roster")


def _sha256(value: object) -> str:
    text = str(value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ValueError("sha256 invalid")
    return text


__all__ = [
    "ResearchCommitteeStorageError",
    "SupabaseResearchCommitteeReadModel",
    "SupabaseResearchCommitteeRepository",
]
