from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Mapping

from investment_research_os.production_execution import (
    EvaluationCorpus,
    MVP_EVALUATION_EXECUTION_ROLES,
)
from investment_research_os.providers.openai_contracts import (
    OpenAIEvaluationExecutionIdentity,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_KEYS = {
    "api_key",
    "authorization",
    "raw_request",
    "raw_response",
    "reasoning_content",
    "encrypted_content",
}


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower() in _FORBIDDEN_KEYS or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class FrozenEvaluationCheck:
    check_id: str
    status: str

    def as_dict(self) -> dict[str, object]:
        return {"check_id": self.check_id, "status": self.status}


@dataclass(frozen=True, slots=True)
class FrozenOpenAIEvaluationReport:
    corpus_id: str
    corpus_version: str
    corpus_content_sha256: str
    case_id: str
    execution_identities: tuple[Mapping[str, str], ...]
    checks: tuple[FrozenEvaluationCheck, ...]
    usage: Mapping[str, int]
    estimated_cost_usd: str
    fixture_content_sha256: str
    content_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": "frozen_evaluation_report.v1",
            "corpus_id": self.corpus_id,
            "corpus_version": self.corpus_version,
            "corpus_content_sha256": self.corpus_content_sha256,
            "case_id": self.case_id,
            "execution_identities": [dict(item) for item in self.execution_identities],
            "checks": [item.as_dict() for item in self.checks],
            "usage": dict(self.usage),
            "estimated_cost_usd": self.estimated_cost_usd,
            "fixture_content_sha256": self.fixture_content_sha256,
            "content_sha256": self.content_sha256,
        }


class FrozenOpenAIEvaluationRunner:
    """Evaluates sanitized fake results for one immutable corpus case."""

    def __init__(
        self,
        *,
        corpus: EvaluationCorpus,
        execution_identities: tuple[
            OpenAIEvaluationExecutionIdentity,
            ...,
        ],
    ) -> None:
        if (
            tuple(item.execution_role for item in execution_identities)
            != MVP_EVALUATION_EXECUTION_ROLES
            or any(
                item.corpus_id != corpus.corpus_id
                or item.corpus_version != corpus.corpus_version
                or item.corpus_content_sha256 != corpus.content_sha256
                for item in execution_identities
            )
            or len({item.evaluation_identity_sha256 for item in execution_identities})
            != len(MVP_EVALUATION_EXECUTION_ROLES)
        ):
            raise ValueError("evaluation execution identities mismatch")
        self._corpus = corpus
        self._identities = execution_identities

    def run(
        self,
        fixture: Mapping[str, object],
    ) -> FrozenOpenAIEvaluationReport:
        expected_fields = {
            "contract_version",
            "corpus_id",
            "corpus_version",
            "corpus_content_sha256",
            "case_id",
            "execution_results",
            "content_sha256",
        }
        if (
            set(fixture) != expected_fields
            or fixture.get("contract_version") != "frozen_evaluation_results.v1"
            or fixture.get("corpus_id") != self._corpus.corpus_id
            or fixture.get("corpus_version") != self._corpus.corpus_version
            or fixture.get("corpus_content_sha256") != self._corpus.content_sha256
            or _contains_forbidden_key(fixture)
        ):
            raise ValueError("invalid frozen evaluation fixture")
        fixture_hash = fixture.get("content_sha256")
        if (
            not isinstance(fixture_hash, str)
            or _SHA256.fullmatch(fixture_hash) is None
            or _sha256(
                {
                    key: value
                    for key, value in fixture.items()
                    if key != "content_sha256"
                }
            )
            != fixture_hash
        ):
            raise ValueError("frozen evaluation fixture hash mismatch")
        case_id = fixture.get("case_id")
        evaluation_case = next(
            (item for item in self._corpus.cases if item.case_id == case_id),
            None,
        )
        if evaluation_case is None:
            raise ValueError("evaluation case absent from corpus")
        values = fixture.get("execution_results")
        if not isinstance(values, list) or len(values) != len(self._identities):
            raise ValueError("evaluation result roster mismatch")

        schema_results: list[bool] = []
        citation_results: list[bool] = []
        synthesis_results: dict[str, bool] = {}
        token_results: list[bool] = []
        cost_results: list[bool] = []
        totals = {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
        }
        total_cost = Decimal("0")
        identity_refs: list[Mapping[str, str]] = []
        for value, identity in zip(values, self._identities, strict=True):
            result = self._validate_result(value, identity)
            checks = result["checks"]
            if identity.execution_role == "synthesizer":
                synthesis_results = dict(checks)
            else:
                schema_results.append(checks["schema_valid"])
                citation_results.append(checks["citation_valid"])
            for key in totals:
                totals[key] += result["usage"][key]
            token_results.append(result["token_valid"])
            cost_results.append(result["cost_valid"])
            total_cost += result["estimated_cost_usd"]
            identity_refs.append(
                {
                    "execution_role": identity.execution_role,
                    "evaluation_identity_sha256": (identity.evaluation_identity_sha256),
                }
            )

        checks = (
            FrozenEvaluationCheck(
                "grader_schema_valid",
                "passed" if all(schema_results) else "failed",
            ),
            FrozenEvaluationCheck(
                "grader_citations_valid",
                "passed" if all(citation_results) else "failed",
            ),
            FrozenEvaluationCheck(
                "synthesis_schema_valid",
                ("passed" if synthesis_results["schema_valid"] else "failed"),
            ),
            FrozenEvaluationCheck(
                "synthesis_provenance_valid",
                ("passed" if synthesis_results["provenance_valid"] else "failed"),
            ),
            FrozenEvaluationCheck(
                "synthesis_authority_valid",
                ("passed" if synthesis_results["authority_valid"] else "failed"),
            ),
            FrozenEvaluationCheck(
                "usage_within_token_caps",
                "passed" if all(token_results) else "failed",
            ),
            FrozenEvaluationCheck(
                "estimated_cost_within_hard_budgets",
                "passed" if all(cost_results) else "failed",
            ),
            FrozenEvaluationCheck(
                "operator_sample_memo_approved",
                "pending_hitl",
            ),
        )
        if tuple(item.check_id for item in checks) != (evaluation_case.expected_checks):
            raise ValueError("evaluation report checks do not match corpus")
        content = {
            "contract_version": "frozen_evaluation_report.v1",
            "corpus_id": self._corpus.corpus_id,
            "corpus_version": self._corpus.corpus_version,
            "corpus_content_sha256": self._corpus.content_sha256,
            "case_id": case_id,
            "execution_identities": [dict(item) for item in identity_refs],
            "checks": [item.as_dict() for item in checks],
            "usage": totals,
            "estimated_cost_usd": format(total_cost, "f"),
            "fixture_content_sha256": fixture_hash,
        }
        return FrozenOpenAIEvaluationReport(
            corpus_id=self._corpus.corpus_id,
            corpus_version=self._corpus.corpus_version,
            corpus_content_sha256=self._corpus.content_sha256,
            case_id=str(case_id),
            execution_identities=tuple(identity_refs),
            checks=checks,
            usage=totals,
            estimated_cost_usd=format(total_cost, "f"),
            fixture_content_sha256=fixture_hash,
            content_sha256=_sha256(content),
        )

    @staticmethod
    def _validate_result(
        value: object,
        identity: OpenAIEvaluationExecutionIdentity,
    ) -> dict[str, object]:
        expected_fields = {
            "execution_role",
            "evaluation_identity_sha256",
            "checks",
            "token_caps",
            "usage",
            "estimated_cost_usd",
            "hard_budget_usd",
        }
        if (
            not isinstance(value, Mapping)
            or set(value) != expected_fields
            or value.get("execution_role") != identity.execution_role
            or value.get("evaluation_identity_sha256")
            != identity.evaluation_identity_sha256
        ):
            raise ValueError("evaluation result identity mismatch")
        checks = value.get("checks")
        expected_checks = (
            {"schema_valid", "provenance_valid", "authority_valid"}
            if identity.execution_role == "synthesizer"
            else {"schema_valid", "citation_valid"}
        )
        if (
            not isinstance(checks, Mapping)
            or set(checks) != expected_checks
            or any(type(item) is not bool for item in checks.values())
        ):
            raise ValueError("invalid evaluation result checks")
        token_caps = value.get("token_caps")
        usage = value.get("usage")
        usage_fields = {
            "input_tokens",
            "cached_input_tokens",
            "cache_write_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        }
        if (
            not isinstance(token_caps, Mapping)
            or set(token_caps) != {"input_tokens", "output_tokens"}
            or any(type(item) is not int or item <= 0 for item in token_caps.values())
            or not isinstance(usage, Mapping)
            or set(usage) != usage_fields
            or any(type(item) is not int or item < 0 for item in usage.values())
            or usage["cached_input_tokens"] + usage["cache_write_tokens"]
            > usage["input_tokens"]
            or usage["reasoning_tokens"] > usage["output_tokens"]
            or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]
        ):
            raise ValueError("invalid evaluation token accounting")
        token_valid = (
            usage["input_tokens"] <= token_caps["input_tokens"]
            and usage["output_tokens"] <= token_caps["output_tokens"]
        )
        try:
            estimated_cost = Decimal(str(value["estimated_cost_usd"]))
            hard_budget = Decimal(str(value["hard_budget_usd"]))
        except (InvalidOperation, KeyError) as error:
            raise ValueError("invalid evaluation cost accounting") from error
        if (
            not estimated_cost.is_finite()
            or estimated_cost < 0
            or not hard_budget.is_finite()
            or hard_budget <= 0
        ):
            raise ValueError("invalid evaluation cost accounting")
        return {
            "checks": dict(checks),
            "usage": dict(usage),
            "token_valid": token_valid,
            "estimated_cost_usd": estimated_cost,
            "cost_valid": estimated_cost <= hard_budget,
        }


__all__ = [
    "FrozenEvaluationCheck",
    "FrozenOpenAIEvaluationReport",
    "FrozenOpenAIEvaluationRunner",
]
