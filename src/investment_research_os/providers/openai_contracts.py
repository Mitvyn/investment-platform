from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from investment_research_os.grader_executions import ProviderRequest
from investment_research_os.production_execution import (
    EvaluationCorpus,
    MVP_EVALUATION_EXECUTION_ROLES,
    PromptTemplate,
)
from investment_research_os.research_runs import (
    PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
    PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
    QUESTION_TYPE_VERSION,
    WORKFLOW_CONFIG_VERSION,
)
from investment_research_os.providers.openai_responses import (
    OpenAIResponseContract,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _text_tuple(value: object, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(f"{field} must contain unique non-empty text")
    return tuple(value)


def _strict_object(
    properties: Mapping[str, object],
    *,
    min_properties: int | None = None,
) -> dict[str, object]:
    schema: dict[str, object] = {
        "type": "object",
        "properties": dict(properties),
        "required": list(properties),
        "additionalProperties": False,
    }
    if min_properties is not None:
        schema["minProperties"] = min_properties
    return schema


def _string(*, enum: tuple[str, ...] | None = None) -> dict[str, object]:
    value: dict[str, object] = {"type": "string", "minLength": 1}
    if enum is not None:
        value["enum"] = list(enum)
    return value


def _nullable(schema: Mapping[str, object]) -> dict[str, object]:
    return {"anyOf": [dict(schema), {"type": "null"}]}


def _array(
    items: Mapping[str, object],
    *,
    min_items: int = 0,
    max_items: int | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "type": "array",
        "items": dict(items),
        "minItems": min_items,
    }
    if max_items is not None:
        value["maxItems"] = max_items
    return value


def _numeric_value_schema() -> dict[str, object]:
    return _strict_object(
        {
            "value": _string(),
            "unit": _string(),
            "calculation_method": _string(),
            "assumptions": _array(_string()),
            "evidence_ids": _array(_string()),
            "calculation_ids": _array(_string()),
        }
    )


def _grader_schema(
    *,
    grader_id: str,
    grader_version: str,
    owned_decision_question: str,
    payload_name: str,
    payload_schema: Mapping[str, object],
) -> dict[str, object]:
    claim = _strict_object(
        {
            "claim_id": _string(),
            "claim": _string(),
            "materiality": _string(enum=("high", "medium", "low")),
            "evidence_ids": _array(_string(), min_items=1),
        }
    )
    contradiction = _strict_object({"evidence_id": _string(), "explanation": _string()})
    gap = _strict_object(
        {
            "gap_id": _string(),
            "description": _string(),
            "required_evidence": _string(),
        }
    )
    proposition = _strict_object(
        {
            "proposition_id": _string(),
            "proposition_version": _string(),
            "rendered_proposition_text": _string(),
            "grader_stance": _nullable(
                _string(enum=("supports", "mixed", "challenges"))
            ),
            "stance_rationale": _nullable(_string()),
        }
    )
    abstention = _strict_object(
        {
            "reason_code": _string(),
            "reason": _string(),
            "missing_or_inadequate_evidence": _array(_string(), min_items=1),
            "evidence_required": _array(_string(), min_items=1),
            "confidence": _string(enum=("high", "medium", "low")),
        }
    )
    return _strict_object(
        {
            "execution_state": _string(enum=("accepted", "abstained")),
            "grader_id": {"type": "string", "const": grader_id},
            "grader_version": {"type": "string", "const": grader_version},
            "owned_decision_question": {
                "type": "string",
                "const": owned_decision_question,
            },
            "stance": _nullable(_string(enum=("supports", "mixed", "challenges"))),
            "confidence": _string(enum=("high", "medium", "low")),
            "summary": _string(),
            "material_claims": _array(claim),
            "assumptions": _array(_string()),
            "contradicting_evidence": _array(contradiction),
            "evidence_gaps": _array(gap),
            "invalidation_signals": _array(_string()),
            "proposition": proposition,
            payload_name: dict(payload_schema),
            "abstention": _nullable(abstention),
        }
    )


def _moonshot_schema() -> dict[str, object]:
    question = "Is the opportunity meaningfully asymmetric?"
    payload = _strict_object(
        {
            "contract_version": {
                "type": "string",
                "const": "moonshot_grader_payload.v1",
            },
            "mission_relevance": _string(
                enum=("material", "limited", "none", "indeterminate")
            ),
            "asymmetry_assessment": _string(
                enum=("credible", "conditional", "not_supported", "indeterminate")
            ),
            "evidence_maturity": _string(
                enum=("clinical", "preclinical", "mixed", "insufficient")
            ),
            "strategic_or_societal_value": _string(
                enum=("material", "limited", "not_supported", "indeterminate")
            ),
            "asymmetry_drivers": _array(_string()),
            "limiting_factors": _array(_string()),
        }
    )
    return _grader_schema(
        grader_id="moonshot",
        grader_version="moonshot-grader-v1",
        owned_decision_question=question,
        payload_name="moonshot_payload",
        payload_schema=payload,
    )


def _catalyst_schema() -> dict[str, object]:
    question = "What event resolves uncertainty, when, and with what outcomes?"
    payload = _strict_object(
        {
            "contract_version": {
                "type": "string",
                "const": "catalyst_grader_payload.v1",
            },
            "catalyst_definition": _string(),
            "programme": _string(),
            "probability": _numeric_value_schema(),
            "timing_window": _string(),
            "date_confidence": _string(enum=("high", "medium", "low")),
            "success_outcome": _string(),
            "delay_outcome": _string(),
            "partial_success_outcome": _string(),
            "failure_outcome": _string(),
        }
    )
    return _grader_schema(
        grader_id="catalyst",
        grader_version="catalyst-grader-v1",
        owned_decision_question=question,
        payload_name="catalyst_payload",
        payload_schema=payload,
    )


def _biotech_schema() -> dict[str, object]:
    question = "Is the scientific and clinical evidence credible?"
    payload = _strict_object(
        {
            "contract_version": {
                "type": "string",
                "const": "biotech_grader_payload.v1",
            },
            "mechanism_plausibility": _string(
                enum=("credible", "mixed", "not_supported", "indeterminate")
            ),
            "preclinical_evidence_quality": _string(
                enum=("strong", "moderate", "weak", "absent")
            ),
            "clinical_evidence_quality": _string(
                enum=("strong", "moderate", "weak", "absent")
            ),
            "trial_design_assessment": _string(),
            "endpoint_relevance": _string(
                enum=("clinically_meaningful", "surrogate", "weak", "indeterminate")
            ),
            "regulatory_credibility": _string(
                enum=("credible", "mixed", "weak", "indeterminate")
            ),
            "claims_exceed_evidence": {"type": "boolean"},
            "limitations": _array(_string()),
        }
    )
    return _grader_schema(
        grader_id="biotech",
        grader_version="biotech-grader-v1",
        owned_decision_question=question,
        payload_name="biotech_payload",
        payload_schema=payload,
    )


def _risk_dilution_schema() -> dict[str, object]:
    question = "Can shareholders survive financially until the thesis resolves?"
    payload = _strict_object(
        {
            "contract_version": {
                "type": "string",
                "const": "risk_dilution_grader_payload.v1",
            },
            "cash_runway": _numeric_value_schema(),
            "burn_rate": _numeric_value_schema(),
            "going_concern_risk": _string(
                enum=("low", "moderate", "high", "indeterminate")
            ),
            "dilution_mechanisms": _array(_string()),
            "financing_required_before_catalyst": _string(
                enum=("no", "possible", "yes", "indeterminate")
            ),
            "downside_mechanisms": _array(_string()),
            "permanent_capital_loss_mechanisms": _array(_string()),
        }
    )
    return _grader_schema(
        grader_id="risk_dilution",
        grader_version="risk_dilution-grader-v1",
        owned_decision_question=question,
        payload_name="risk_dilution_payload",
        payload_schema=payload,
    )


def _valuation_schema() -> dict[str, object]:
    question = "What outcomes and assumptions justify the current or implied value?"
    scenario = _strict_object(
        {
            "scenario_id": _string(),
            "case": _string(enum=("conservative", "base", "bull", "failure")),
            "probability": _numeric_value_schema(),
            "equity_value": _numeric_value_schema(),
            "implied_value_per_diluted_share": _numeric_value_schema(),
            "assumptions": _array(_string()),
        }
    )
    payload = _strict_object(
        {
            "contract_version": {
                "type": "string",
                "const": "valuation_grader_payload.v1",
            },
            "valuation_method": _string(),
            "current_market_value": _numeric_value_schema(),
            "fully_diluted_shares": _numeric_value_schema(),
            "scenarios": _array(scenario, min_items=4, max_items=4),
            "sensitivities": _array(_string()),
        }
    )
    return _grader_schema(
        grader_id="valuation",
        grader_version="valuation-grader-v1",
        owned_decision_question=question,
        payload_name="valuation_payload",
        payload_schema=payload,
    )


def _synthesizer_schema() -> dict[str, object]:
    statement = _strict_object(
        {
            "statement_id": _string(),
            "text": _string(),
            "provenance_type": _string(
                enum=(
                    "fact",
                    "grader_interpretation",
                    "synthesis_interpretation",
                    "assumption",
                    "gap",
                )
            ),
            "evidence_ids": _array(_string()),
            "opinion_ids": _array(_string()),
            "calculation_ids": _array(_string()),
        }
    )
    disagreement = _strict_object(
        {
            "disagreement_id": _string(),
            "disputed_question_statement_id": _string(),
            "position_statement_ids": _array(_string(), min_items=2),
            "contributing_opinion_ids": _array(_string(), min_items=2),
            "affects_disposition": {"type": "boolean"},
            "resolving_evidence_statement_ids": _array(
                _string(),
                min_items=1,
            ),
        }
    )
    review_trigger = _strict_object(
        {
            "trigger_type": _string(enum=("date", "evidence_event")),
            "review_at": _nullable(_string()),
            "statement_id": _string(),
        }
    )
    disclosure = _strict_object(
        {
            "grader_id": _string(),
            "execution_state": _string(
                enum=(
                    "accepted",
                    "abstained",
                    "failed",
                    "not_eligible",
                    "not_executed",
                )
            ),
            "opinion_id": _nullable(_string()),
            "stance": _nullable(_string(enum=("supports", "mixed", "challenges"))),
        }
    )
    statement_ids = _array(_string())
    return _strict_object(
        {
            "requested_disposition": _string(
                enum=("reject", "monitor", "deep_research", "decision_ready")
            ),
            "executive_summary_statement_ids": statement_ids,
            "statements": _array(statement, min_items=1),
            "common_ground_statement_ids": statement_ids,
            "disagreement_records": _array(disagreement),
            "disputed_assumption_statement_ids": statement_ids,
            "evidence_gap_statement_ids": statement_ids,
            "invalidation_statement_ids": statement_ids,
            "required_next_evidence_statement_ids": statement_ids,
            "review_trigger": review_trigger,
            "state_disclosure": _array(disclosure, min_items=5, max_items=5),
        }
    )


_OUTPUT_SCHEMAS = {
    "grader:moonshot": _moonshot_schema(),
    "grader:catalyst": _catalyst_schema(),
    "grader:biotech": _biotech_schema(),
    "grader:risk_dilution": _risk_dilution_schema(),
    "grader:valuation": _valuation_schema(),
    "synthesizer": _synthesizer_schema(),
}


def _validate_strict_schema(schema: object) -> None:
    if not isinstance(schema, Mapping):
        raise ValueError("output schema must be an object")
    schema_type = schema.get("type")
    if schema_type == "object":
        properties = schema.get("properties")
        required = schema.get("required")
        if (
            not isinstance(properties, Mapping)
            or schema.get("additionalProperties") is not False
            or required != list(properties)
        ):
            raise ValueError("output object schema must be strict")
        for child in properties.values():
            _validate_strict_schema(child)
    elif schema_type == "array":
        _validate_strict_schema(schema.get("items"))
    elif "anyOf" in schema:
        options = schema["anyOf"]
        if not isinstance(options, list) or not options:
            raise ValueError("output schema anyOf must be non-empty")
        for child in options:
            _validate_strict_schema(child)
    elif schema_type not in {"string", "boolean", "null"}:
        raise ValueError("unsupported output schema type")


@dataclass(frozen=True, slots=True)
class OpenAIExecutionContract:
    execution_role: str
    execution_contract_version: str
    owned_decision_question: str
    eligibility_rule_version: str
    eligibility_rules: tuple[str, ...]
    rubric_version: str
    rubric: tuple[str, ...]
    abstention_rule_version: str
    abstention_rules: tuple[str, ...]
    authority_rules: tuple[str, ...]
    prompt: PromptTemplate
    output_schema_name: str
    output_schema: Mapping[str, object]
    output_schema_content_sha256: str
    content_sha256: str

    def logical_input_contract(self) -> dict[str, object]:
        return {
            "execution_contract_version": self.execution_contract_version,
            "content_sha256": self.content_sha256,
            "owned_decision_question": self.owned_decision_question,
            "eligibility_rule_version": self.eligibility_rule_version,
            "eligibility_rules": list(self.eligibility_rules),
            "rubric_version": self.rubric_version,
            "rubric": list(self.rubric),
            "abstention_rule_version": self.abstention_rule_version,
            "abstention_rules": list(self.abstention_rules),
            "authority_rules": list(self.authority_rules),
            "output_schema_content_sha256": self.output_schema_content_sha256,
        }

    def validate_logical_input(
        self,
        logical_input: Mapping[str, object],
    ) -> None:
        if self.execution_role.startswith("grader:"):
            expected_keys = {
                "bundle",
                "evidence_passages",
                "valuation_snapshot",
                "question_type_id",
                "question_type_version",
                "workflow_config_version",
                "proposition_id",
                "proposition_version",
                "rendered_proposition",
                "grader",
                "execution_contract",
            }
            grader = logical_input.get("grader")
            if (
                set(logical_input) != expected_keys
                or not isinstance(grader, Mapping)
                or grader.get("grader_id")
                != self.execution_role.removeprefix("grader:")
                or logical_input.get("execution_contract")
                != self.logical_input_contract()
            ):
                raise ValueError("grader logical input boundary violation")
            return
        expected_keys = {
            "committee",
            "calculation_ids",
            "authority",
            "prompt",
            "execution_contract",
        }
        committee = logical_input.get("committee")
        grader_results = (
            committee.get("grader_results") if isinstance(committee, Mapping) else None
        )
        expected_committee_keys = {
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
        if (
            set(logical_input) != expected_keys
            or logical_input.get("authority") != "reconciliation_only"
            or logical_input.get("execution_contract") != self.logical_input_contract()
            or not isinstance(logical_input.get("calculation_ids"), list)
            or not isinstance(committee, Mapping)
            or set(committee) != expected_committee_keys
            or committee.get("contract_version") != "committee_state.v1"
            or not isinstance(grader_results, list)
            or len(grader_results) != 5
            or not self._valid_synthesis_grader_results(grader_results)
        ):
            raise ValueError("synthesizer logical input boundary violation")

    @staticmethod
    def _valid_synthesis_grader_results(values: list[object]) -> bool:
        expected_keys = {
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
        expected_ids = tuple(
            role.removeprefix("grader:") for role in MVP_EVALUATION_EXECUTION_ROLES[:-1]
        )
        states = {
            "accepted",
            "abstained",
            "failed",
            "not_eligible",
            "not_executed",
        }
        for value, grader_id in zip(values, expected_ids, strict=True):
            if (
                not isinstance(value, Mapping)
                or set(value) != expected_keys
                or value.get("contract_version") != "committee_grader_result.v1"
                or value.get("grader_id") != grader_id
                or value.get("execution_state") not in states
            ):
                return False
            opinion = value.get("opinion")
            if value["execution_state"] in {"accepted", "abstained"}:
                if not OpenAIExecutionContract._valid_synthesis_opinion(
                    opinion,
                    grader_id,
                    str(value["execution_state"]),
                ):
                    return False
            elif opinion is not None:
                return False
        return True

    @staticmethod
    def _valid_synthesis_opinion(
        value: object,
        grader_id: str,
        execution_state: str,
    ) -> bool:
        expected_keys = {
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
        if not isinstance(value, Mapping) or set(value) != expected_keys:
            return False
        metadata = value.get("execution_metadata")
        if (
            not isinstance(metadata, Mapping)
            or metadata.get("grader_execution_contract_version")
            != "grader_execution.v1"
        ):
            return False
        if execution_state == "accepted":
            return (
                value.get("stance")
                in {
                    "supports",
                    "mixed",
                    "challenges",
                }
                and value.get("abstention") is None
            )
        return value.get("stance") is None and isinstance(
            value.get("abstention"),
            Mapping,
        )

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, object],
        *,
        prompt: PromptTemplate,
    ) -> OpenAIExecutionContract:
        expected_keys = {
            "contract_version",
            "execution_role",
            "execution_contract_version",
            "owned_decision_question",
            "eligibility_rule_version",
            "eligibility_rules",
            "rubric_version",
            "rubric",
            "abstention_rule_version",
            "abstention_rules",
            "authority_rules",
            "prompt_id",
            "prompt_version",
            "prompt_content_sha256",
            "input_schema_version",
            "output_schema_version",
            "output_schema_name",
            "output_schema_content_sha256",
            "content_sha256",
        }
        if set(value) != expected_keys:
            raise ValueError("invalid OpenAI execution contract fields")
        if value.get("contract_version") != "openai_execution_contract.v1":
            raise ValueError("unsupported OpenAI execution contract")
        execution_role = _text(value["execution_role"], "execution_role")
        if execution_role != prompt.execution_role:
            raise ValueError("execution contract prompt role mismatch")
        prompt_binding = {
            "prompt_id": prompt.prompt_id,
            "prompt_version": prompt.prompt_version,
            "prompt_content_sha256": prompt.content_sha256,
            "input_schema_version": prompt.input_schema_version,
            "output_schema_version": prompt.output_schema_version,
        }
        if any(value.get(key) != expected for key, expected in prompt_binding.items()):
            raise ValueError("execution contract prompt binding mismatch")
        output_schema = _OUTPUT_SCHEMAS.get(execution_role)
        if output_schema is None:
            raise ValueError("unsupported OpenAI execution role")
        _validate_strict_schema(output_schema)
        output_schema_hash = _text(
            value["output_schema_content_sha256"],
            "output_schema_content_sha256",
        )
        if not _SHA256.fullmatch(output_schema_hash):
            raise ValueError("invalid output schema content hash")
        if _sha256(output_schema) != output_schema_hash:
            raise ValueError("output schema content hash mismatch")
        content = {key: value[key] for key in expected_keys - {"content_sha256"}}
        content_hash = _text(value["content_sha256"], "content_sha256")
        if not _SHA256.fullmatch(content_hash):
            raise ValueError("invalid execution contract content hash")
        if _sha256(content) != content_hash:
            raise ValueError("execution contract content hash mismatch")
        return cls(
            execution_role=execution_role,
            execution_contract_version=_text(
                value["execution_contract_version"],
                "execution_contract_version",
            ),
            owned_decision_question=_text(
                value["owned_decision_question"],
                "owned_decision_question",
            ),
            eligibility_rule_version=_text(
                value["eligibility_rule_version"],
                "eligibility_rule_version",
            ),
            eligibility_rules=_text_tuple(
                value["eligibility_rules"],
                "eligibility_rules",
            ),
            rubric_version=_text(value["rubric_version"], "rubric_version"),
            rubric=_text_tuple(value["rubric"], "rubric"),
            abstention_rule_version=_text(
                value["abstention_rule_version"],
                "abstention_rule_version",
            ),
            abstention_rules=_text_tuple(
                value["abstention_rules"],
                "abstention_rules",
            ),
            authority_rules=_text_tuple(
                value["authority_rules"],
                "authority_rules",
            ),
            prompt=prompt,
            output_schema_name=_text(
                value["output_schema_name"],
                "output_schema_name",
            ),
            output_schema=output_schema,
            output_schema_content_sha256=output_schema_hash,
            content_sha256=content_hash,
        )

    def as_response_contract(self) -> OpenAIResponseContract:
        return OpenAIResponseContract(
            execution_role=self.execution_role,
            prompt_id=self.prompt.prompt_id,
            prompt_version=self.prompt.prompt_version,
            prompt_content_sha256=self.prompt.content_sha256,
            input_schema_version=self.prompt.input_schema_version,
            output_schema_version=self.prompt.output_schema_version,
            system_instructions=self.prompt.system_instructions,
            task_template=self.prompt.task_template,
            output_schema_name=self.output_schema_name,
            output_schema=self.output_schema,
        )


@dataclass(frozen=True, slots=True)
class OpenAIEvaluationExecutionIdentity:
    execution_role: str
    execution_contract_version: str
    execution_contract_content_sha256: str
    output_schema_version: str
    output_schema_content_sha256: str
    prompt_id: str
    prompt_version: str
    prompt_content_sha256: str
    model_config_id: str
    model_config_version: str
    inference_parameter_hash: str
    price_card_id: str
    price_card_content_sha256: str
    corpus_id: str
    corpus_version: str
    corpus_content_sha256: str
    evaluation_identity_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        contract: OpenAIExecutionContract,
        model_config_id: str,
        model_config_version: str,
        inference_parameter_hash: str,
        price_card_id: str,
        price_card_content_sha256: str,
        corpus: EvaluationCorpus,
    ) -> OpenAIEvaluationExecutionIdentity:
        if contract.execution_role not in corpus.execution_roles:
            raise ValueError("evaluation role absent from corpus")
        values = {
            "execution_role": contract.execution_role,
            "execution_contract_version": contract.execution_contract_version,
            "execution_contract_content_sha256": contract.content_sha256,
            "output_schema_version": contract.prompt.output_schema_version,
            "output_schema_content_sha256": (contract.output_schema_content_sha256),
            "prompt_id": contract.prompt.prompt_id,
            "prompt_version": contract.prompt.prompt_version,
            "prompt_content_sha256": contract.prompt.content_sha256,
            "model_config_id": model_config_id,
            "model_config_version": model_config_version,
            "inference_parameter_hash": inference_parameter_hash,
            "price_card_id": price_card_id,
            "price_card_content_sha256": price_card_content_sha256,
            "corpus_id": corpus.corpus_id,
            "corpus_version": corpus.corpus_version,
            "corpus_content_sha256": corpus.content_sha256,
        }
        for key, value in values.items():
            _text(value, key)
        for key in (
            "execution_contract_content_sha256",
            "output_schema_content_sha256",
            "prompt_content_sha256",
            "inference_parameter_hash",
            "price_card_content_sha256",
            "corpus_content_sha256",
        ):
            if _SHA256.fullmatch(values[key]) is None:
                raise ValueError(f"invalid {key}")
        content = {
            "contract_version": "openai_evaluation_execution_identity.v2",
            **values,
        }
        return cls(
            **values,
            evaluation_identity_sha256=_sha256(content),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": "openai_evaluation_execution_identity.v2",
            "execution_role": self.execution_role,
            "execution_contract_version": self.execution_contract_version,
            "execution_contract_content_sha256": (
                self.execution_contract_content_sha256
            ),
            "output_schema_version": self.output_schema_version,
            "output_schema_content_sha256": (self.output_schema_content_sha256),
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "prompt_content_sha256": self.prompt_content_sha256,
            "model_config_id": self.model_config_id,
            "model_config_version": self.model_config_version,
            "inference_parameter_hash": self.inference_parameter_hash,
            "price_card_id": self.price_card_id,
            "price_card_content_sha256": self.price_card_content_sha256,
            "corpus_id": self.corpus_id,
            "corpus_version": self.corpus_version,
            "corpus_content_sha256": self.corpus_content_sha256,
            "evaluation_identity_sha256": (self.evaluation_identity_sha256),
        }


@dataclass(frozen=True, slots=True)
class OpenAIExecutionContractRegistry:
    question_type_version: str
    workflow_config_version: str
    contracts: tuple[OpenAIExecutionContract, ...]
    content_sha256: str

    @property
    def execution_roles(self) -> tuple[str, ...]:
        return tuple(item.execution_role for item in self.contracts)

    def for_research_contract(
        self,
        *,
        question_type_version: str,
        workflow_config_version: str,
    ) -> OpenAIExecutionContractRegistry:
        """Bind frozen role contracts to one approved research identity."""

        source_identity = (
            self.question_type_version,
            self.workflow_config_version,
        )
        target_identity = (question_type_version, workflow_config_version)
        strict_identity = (QUESTION_TYPE_VERSION, WORKFLOW_CONFIG_VERSION)
        personal_identity = (
            PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
            PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
        )
        if target_identity == source_identity:
            return self
        if source_identity != strict_identity or target_identity != personal_identity:
            raise ValueError("unsupported execution contract research identity")
        binding_hash = _sha256(
            {
                "source_registry_content_sha256": self.content_sha256,
                "question_type_version": question_type_version,
                "workflow_config_version": workflow_config_version,
            }
        )
        return OpenAIExecutionContractRegistry(
            question_type_version=question_type_version,
            workflow_config_version=workflow_config_version,
            contracts=self.contracts,
            content_sha256=binding_hash,
        )

    @classmethod
    def load(
        cls,
        *,
        contract_path: Path,
        prompt_path: Path,
    ) -> OpenAIExecutionContractRegistry:
        contract_payload = json.loads(contract_path.read_text())
        prompt_payload = json.loads(prompt_path.read_text())
        if not isinstance(contract_payload, dict) or set(contract_payload) != {
            "contract_version",
            "question_type_version",
            "workflow_config_version",
            "execution_roles",
            "contracts",
            "content_sha256",
        }:
            raise ValueError("invalid OpenAI execution contract registry fields")
        if (
            contract_payload.get("contract_version")
            != "openai_execution_contract_registry.v1"
        ):
            raise ValueError("unsupported OpenAI execution contract registry")
        if not isinstance(prompt_payload, dict) or set(prompt_payload) != {
            "contract_version",
            "question_type_version",
            "workflow_config_version",
            "templates",
        }:
            raise ValueError("invalid prompt registry fields")
        if (
            prompt_payload.get("contract_version") != "prompt_registry.v1"
            or prompt_payload.get("question_type_version")
            != contract_payload.get("question_type_version")
            or prompt_payload.get("workflow_config_version")
            != contract_payload.get("workflow_config_version")
        ):
            raise ValueError("execution contract prompt registry mismatch")
        prompt_values = prompt_payload.get("templates")
        contract_values = contract_payload.get("contracts")
        if not isinstance(prompt_values, list) or not isinstance(
            contract_values,
            list,
        ):
            raise ValueError("invalid execution contract registry entries")
        prompts = tuple(PromptTemplate.from_dict(item) for item in prompt_values)
        if tuple(item.execution_role for item in prompts) != (
            MVP_EVALUATION_EXECUTION_ROLES
        ):
            raise ValueError("prompt registry execution roster mismatch")
        if tuple(contract_payload.get("execution_roles", ())) != (
            MVP_EVALUATION_EXECUTION_ROLES
        ):
            raise ValueError("execution contract registry roster mismatch")
        if len(contract_values) != len(prompts):
            raise ValueError("execution contract registry roster mismatch")
        contracts = tuple(
            OpenAIExecutionContract.from_dict(value, prompt=prompt)
            for value, prompt in zip(contract_values, prompts, strict=True)
        )
        if tuple(item.execution_role for item in contracts) != (
            MVP_EVALUATION_EXECUTION_ROLES
        ):
            raise ValueError("execution contract registry roster mismatch")
        content = {
            key: contract_payload[key]
            for key in contract_payload
            if key != "content_sha256"
        }
        content_hash = _text(
            contract_payload["content_sha256"],
            "content_sha256",
        )
        if not _SHA256.fullmatch(content_hash):
            raise ValueError("invalid execution contract registry content hash")
        if _sha256(content) != content_hash:
            raise ValueError("execution contract registry content hash mismatch")
        return cls(
            question_type_version=_text(
                contract_payload["question_type_version"],
                "question_type_version",
            ),
            workflow_config_version=_text(
                contract_payload["workflow_config_version"],
                "workflow_config_version",
            ),
            contracts=contracts,
            content_sha256=content_hash,
        )

    def resolve(self, request: ProviderRequest) -> OpenAIResponseContract:
        matches = [
            item
            for item in self.contracts
            if item.execution_role == request.execution_role
        ]
        if len(matches) != 1:
            raise ValueError("OpenAI execution role is not uniquely registered")
        contract = matches[0]
        contract.validate_logical_input(request.logical_input)
        return contract.as_response_contract()


__all__ = [
    "OpenAIEvaluationExecutionIdentity",
    "OpenAIExecutionContract",
    "OpenAIExecutionContractRegistry",
]
