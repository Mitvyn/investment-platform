from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
MVP_EVALUATION_EXECUTION_ROLES = (
    "grader:moonshot",
    "grader:catalyst",
    "grader:biotech",
    "grader:risk_dilution",
    "grader:valuation",
    "synthesizer",
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def evaluation_execution_identity_sha256(
    *,
    execution_role: str,
    execution_contract_version: str,
    prompt_id: str,
    prompt_version: str,
    prompt_content_sha256: str,
    model_config_id: str,
    model_config_version: str,
    inference_parameter_hash: str,
    corpus_id: str,
    corpus_version: str,
    corpus_content_sha256: str,
) -> str:
    content = EvaluationExecutionIdentity._validated_content(
        {
            "contract_version": "evaluation_execution_identity.v1",
            "execution_role": execution_role,
            "execution_contract_version": execution_contract_version,
            "prompt_id": prompt_id,
            "prompt_version": prompt_version,
            "prompt_content_sha256": prompt_content_sha256,
            "model_config_id": model_config_id,
            "model_config_version": model_config_version,
            "inference_parameter_hash": inference_parameter_hash,
            "corpus_id": corpus_id,
            "corpus_version": corpus_version,
            "corpus_content_sha256": corpus_content_sha256,
        }
    )
    return _sha256(content)


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    prompt_id: str
    prompt_version: str
    execution_role: str
    input_schema_version: str
    output_schema_version: str
    system_instructions: tuple[str, ...]
    task_template: str
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        prompt_id: str,
        prompt_version: str,
        execution_role: str,
        input_schema_version: str,
        output_schema_version: str,
        system_instructions: tuple[str, ...],
        task_template: str,
    ) -> PromptTemplate:
        content = cls._validated_content(
            {
                "contract_version": "prompt_template.v1",
                "prompt_id": prompt_id,
                "prompt_version": prompt_version,
                "execution_role": execution_role,
                "input_schema_version": input_schema_version,
                "output_schema_version": output_schema_version,
                "system_instructions": list(system_instructions),
                "task_template": task_template,
            }
        )
        return cls(
            prompt_id=content["prompt_id"],
            prompt_version=content["prompt_version"],
            execution_role=content["execution_role"],
            input_schema_version=content["input_schema_version"],
            output_schema_version=content["output_schema_version"],
            system_instructions=tuple(content["system_instructions"]),
            task_template=content["task_template"],
            content_sha256=_sha256(content),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PromptTemplate:
        expected_keys = {
            "contract_version",
            "prompt_id",
            "prompt_version",
            "execution_role",
            "input_schema_version",
            "output_schema_version",
            "system_instructions",
            "task_template",
            "content_sha256",
        }
        if set(value) != expected_keys:
            raise ValueError("invalid prompt template fields")
        content = cls._validated_content(
            {key: value[key] for key in expected_keys - {"content_sha256"}}
        )
        content_sha256 = _require_text(
            value["content_sha256"],
            "content_sha256",
        )
        if not _SHA256.fullmatch(content_sha256):
            raise ValueError("invalid prompt template content hash")
        if _sha256(content) != content_sha256:
            raise ValueError("prompt template content hash mismatch")
        return cls(
            prompt_id=content["prompt_id"],
            prompt_version=content["prompt_version"],
            execution_role=content["execution_role"],
            input_schema_version=content["input_schema_version"],
            output_schema_version=content["output_schema_version"],
            system_instructions=tuple(content["system_instructions"]),
            task_template=content["task_template"],
            content_sha256=content_sha256,
        )

    @staticmethod
    def _validated_content(value: Mapping[str, object]) -> dict[str, object]:
        if value.get("contract_version") != "prompt_template.v1":
            raise ValueError("unsupported prompt template contract")
        instructions = value.get("system_instructions")
        if (
            not isinstance(instructions, (list, tuple))
            or not instructions
            or any(
                not isinstance(item, str) or not item.strip()
                for item in instructions
            )
        ):
            raise ValueError("system_instructions must contain non-empty text")
        return {
            "contract_version": "prompt_template.v1",
            "prompt_id": _require_text(value.get("prompt_id"), "prompt_id"),
            "prompt_version": _require_text(
                value.get("prompt_version"),
                "prompt_version",
            ),
            "execution_role": _require_text(
                value.get("execution_role"),
                "execution_role",
            ),
            "input_schema_version": _require_text(
                value.get("input_schema_version"),
                "input_schema_version",
            ),
            "output_schema_version": _require_text(
                value.get("output_schema_version"),
                "output_schema_version",
            ),
            "system_instructions": list(instructions),
            "task_template": _require_text(
                value.get("task_template"),
                "task_template",
            ),
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": "prompt_template.v1",
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "execution_role": self.execution_role,
            "input_schema_version": self.input_schema_version,
            "output_schema_version": self.output_schema_version,
            "system_instructions": list(self.system_instructions),
            "task_template": self.task_template,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    evidence_bundle_id: str
    evidence_bundle_hash: str
    fixture_sha256: str
    expected_checks: tuple[str, ...]

    def __post_init__(self) -> None:
        for field in ("case_id", "evidence_bundle_id"):
            _require_text(getattr(self, field), field)
        for field in ("evidence_bundle_hash", "fixture_sha256"):
            if not _SHA256.fullmatch(getattr(self, field)):
                raise ValueError(f"invalid {field}")
        if (
            not self.expected_checks
            or any(not item.strip() for item in self.expected_checks)
            or len(set(self.expected_checks)) != len(self.expected_checks)
        ):
            raise ValueError("expected_checks must be unique non-empty text")

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> EvaluationCase:
        expected_keys = {
            "case_id",
            "evidence_bundle_id",
            "evidence_bundle_hash",
            "fixture_sha256",
            "expected_checks",
        }
        if set(value) != expected_keys:
            raise ValueError("invalid evaluation case fields")
        checks = value["expected_checks"]
        if not isinstance(checks, list) or any(
            not isinstance(item, str) for item in checks
        ):
            raise ValueError("invalid expected_checks")
        return cls(
            case_id=_require_text(value["case_id"], "case_id"),
            evidence_bundle_id=_require_text(
                value["evidence_bundle_id"],
                "evidence_bundle_id",
            ),
            evidence_bundle_hash=_require_text(
                value["evidence_bundle_hash"],
                "evidence_bundle_hash",
            ),
            fixture_sha256=_require_text(
                value["fixture_sha256"],
                "fixture_sha256",
            ),
            expected_checks=tuple(checks),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "evidence_bundle_id": self.evidence_bundle_id,
            "evidence_bundle_hash": self.evidence_bundle_hash,
            "fixture_sha256": self.fixture_sha256,
            "expected_checks": list(self.expected_checks),
        }


@dataclass(frozen=True, slots=True)
class EvaluationCorpus:
    corpus_id: str
    corpus_version: str
    question_type_version: str
    workflow_config_version: str
    evaluation_policy_version: str
    execution_roles: tuple[str, ...]
    cases: tuple[EvaluationCase, ...]
    content_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        corpus_id: str,
        corpus_version: str,
        question_type_version: str,
        workflow_config_version: str,
        evaluation_policy_version: str,
        execution_roles: tuple[str, ...],
        cases: tuple[EvaluationCase, ...],
    ) -> EvaluationCorpus:
        content = cls._validated_content(
            {
                "contract_version": "evaluation_corpus.v1",
                "corpus_id": corpus_id,
                "corpus_version": corpus_version,
                "question_type_version": question_type_version,
                "workflow_config_version": workflow_config_version,
                "evaluation_policy_version": evaluation_policy_version,
                "execution_roles": list(execution_roles),
                "cases": [item.as_dict() for item in cases],
            }
        )
        return cls._from_content(content, _sha256(content))

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> EvaluationCorpus:
        expected_keys = {
            "contract_version",
            "corpus_id",
            "corpus_version",
            "question_type_version",
            "workflow_config_version",
            "evaluation_policy_version",
            "execution_roles",
            "cases",
            "content_sha256",
        }
        if set(value) != expected_keys:
            raise ValueError("invalid evaluation corpus fields")
        content = cls._validated_content(
            {key: value[key] for key in expected_keys - {"content_sha256"}}
        )
        content_sha256 = _require_text(
            value["content_sha256"],
            "content_sha256",
        )
        if not _SHA256.fullmatch(content_sha256):
            raise ValueError("invalid evaluation corpus content hash")
        if _sha256(content) != content_sha256:
            raise ValueError("evaluation corpus content hash mismatch")
        return cls._from_content(content, content_sha256)

    @staticmethod
    def _validated_content(value: Mapping[str, object]) -> dict[str, object]:
        if value.get("contract_version") != "evaluation_corpus.v1":
            raise ValueError("unsupported evaluation corpus contract")
        roles = value.get("execution_roles")
        if (
            not isinstance(roles, (list, tuple))
            or not roles
            or any(not isinstance(item, str) or not item.strip() for item in roles)
            or len(set(roles)) != len(roles)
        ):
            raise ValueError("execution_roles must be unique non-empty text")
        if tuple(roles) != MVP_EVALUATION_EXECUTION_ROLES:
            raise ValueError("evaluation corpus execution roster mismatch")
        raw_cases = value.get("cases")
        if not isinstance(raw_cases, (list, tuple)) or not raw_cases:
            raise ValueError("evaluation corpus requires cases")
        cases = tuple(
            item
            if isinstance(item, EvaluationCase)
            else EvaluationCase.from_dict(item)
            for item in raw_cases
        )
        if len({item.case_id for item in cases}) != len(cases):
            raise ValueError("evaluation case IDs must be unique")
        ordered_cases = sorted(cases, key=lambda item: item.case_id)
        return {
            "contract_version": "evaluation_corpus.v1",
            "corpus_id": _require_text(value.get("corpus_id"), "corpus_id"),
            "corpus_version": _require_text(
                value.get("corpus_version"),
                "corpus_version",
            ),
            "question_type_version": _require_text(
                value.get("question_type_version"),
                "question_type_version",
            ),
            "workflow_config_version": _require_text(
                value.get("workflow_config_version"),
                "workflow_config_version",
            ),
            "evaluation_policy_version": _require_text(
                value.get("evaluation_policy_version"),
                "evaluation_policy_version",
            ),
            "execution_roles": list(roles),
            "cases": [item.as_dict() for item in ordered_cases],
        }

    @classmethod
    def _from_content(
        cls,
        content: Mapping[str, object],
        content_sha256: str,
    ) -> EvaluationCorpus:
        return cls(
            corpus_id=str(content["corpus_id"]),
            corpus_version=str(content["corpus_version"]),
            question_type_version=str(content["question_type_version"]),
            workflow_config_version=str(content["workflow_config_version"]),
            evaluation_policy_version=str(
                content["evaluation_policy_version"]
            ),
            execution_roles=tuple(content["execution_roles"]),
            cases=tuple(
                EvaluationCase.from_dict(item) for item in content["cases"]
            ),
            content_sha256=content_sha256,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": "evaluation_corpus.v1",
            "corpus_id": self.corpus_id,
            "corpus_version": self.corpus_version,
            "question_type_version": self.question_type_version,
            "workflow_config_version": self.workflow_config_version,
            "evaluation_policy_version": self.evaluation_policy_version,
            "execution_roles": list(self.execution_roles),
            "cases": [item.as_dict() for item in self.cases],
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class EvaluationExecutionIdentity:
    execution_role: str
    execution_contract_version: str
    prompt_id: str
    prompt_version: str
    prompt_content_sha256: str
    model_config_id: str
    model_config_version: str
    inference_parameter_hash: str
    corpus_id: str
    corpus_version: str
    corpus_content_sha256: str
    evaluation_identity_sha256: str

    @classmethod
    def freeze(
        cls,
        *,
        execution_role: str,
        execution_contract_version: str,
        prompt: PromptTemplate,
        model_config_id: str,
        model_config_version: str,
        inference_parameter_hash: str,
        corpus: EvaluationCorpus,
    ) -> EvaluationExecutionIdentity:
        if execution_role not in corpus.execution_roles:
            raise ValueError("evaluation role absent from corpus")
        if prompt.execution_role != execution_role:
            raise ValueError("prompt execution role mismatch")
        content = cls._validated_content(
            {
                "contract_version": "evaluation_execution_identity.v1",
                "execution_role": execution_role,
                "execution_contract_version": execution_contract_version,
                "prompt_id": prompt.prompt_id,
                "prompt_version": prompt.prompt_version,
                "prompt_content_sha256": prompt.content_sha256,
                "model_config_id": model_config_id,
                "model_config_version": model_config_version,
                "inference_parameter_hash": inference_parameter_hash,
                "corpus_id": corpus.corpus_id,
                "corpus_version": corpus.corpus_version,
                "corpus_content_sha256": corpus.content_sha256,
            }
        )
        return cls._from_content(content, _sha256(content))

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, object],
    ) -> EvaluationExecutionIdentity:
        expected_keys = {
            "contract_version",
            "execution_role",
            "execution_contract_version",
            "prompt_id",
            "prompt_version",
            "prompt_content_sha256",
            "model_config_id",
            "model_config_version",
            "inference_parameter_hash",
            "corpus_id",
            "corpus_version",
            "corpus_content_sha256",
            "evaluation_identity_sha256",
        }
        if set(value) != expected_keys:
            raise ValueError("invalid evaluation execution identity fields")
        content = cls._validated_content(
            {
                key: value[key]
                for key in expected_keys - {"evaluation_identity_sha256"}
            }
        )
        identity = _require_text(
            value["evaluation_identity_sha256"],
            "evaluation_identity_sha256",
        )
        if not _SHA256.fullmatch(identity):
            raise ValueError("invalid evaluation execution identity hash")
        if _sha256(content) != identity:
            raise ValueError("evaluation execution identity hash mismatch")
        return cls._from_content(content, identity)

    @staticmethod
    def _validated_content(value: Mapping[str, object]) -> dict[str, str]:
        if value.get("contract_version") != "evaluation_execution_identity.v1":
            raise ValueError("unsupported evaluation execution identity contract")
        content = {
            key: _require_text(value.get(key), key)
            for key in (
                "execution_role",
                "execution_contract_version",
                "prompt_id",
                "prompt_version",
                "prompt_content_sha256",
                "model_config_id",
                "model_config_version",
                "inference_parameter_hash",
                "corpus_id",
                "corpus_version",
                "corpus_content_sha256",
            )
        }
        for key in (
            "prompt_content_sha256",
            "inference_parameter_hash",
            "corpus_content_sha256",
        ):
            if not _SHA256.fullmatch(content[key]):
                raise ValueError(f"invalid {key}")
        return {
            "contract_version": "evaluation_execution_identity.v1",
            **content,
        }

    @classmethod
    def _from_content(
        cls,
        content: Mapping[str, str],
        identity: str,
    ) -> EvaluationExecutionIdentity:
        return cls(
            execution_role=content["execution_role"],
            execution_contract_version=content[
                "execution_contract_version"
            ],
            prompt_id=content["prompt_id"],
            prompt_version=content["prompt_version"],
            prompt_content_sha256=content["prompt_content_sha256"],
            model_config_id=content["model_config_id"],
            model_config_version=content["model_config_version"],
            inference_parameter_hash=content["inference_parameter_hash"],
            corpus_id=content["corpus_id"],
            corpus_version=content["corpus_version"],
            corpus_content_sha256=content["corpus_content_sha256"],
            evaluation_identity_sha256=identity,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": "evaluation_execution_identity.v1",
            "execution_role": self.execution_role,
            "execution_contract_version": self.execution_contract_version,
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "prompt_content_sha256": self.prompt_content_sha256,
            "model_config_id": self.model_config_id,
            "model_config_version": self.model_config_version,
            "inference_parameter_hash": self.inference_parameter_hash,
            "corpus_id": self.corpus_id,
            "corpus_version": self.corpus_version,
            "corpus_content_sha256": self.corpus_content_sha256,
            "evaluation_identity_sha256": (
                self.evaluation_identity_sha256
            ),
        }


from investment_research_os.production_execution.preflight import (  # noqa: E402
    AUTHORIZATION_MANIFEST_CONTRACT as AUTHORIZATION_MANIFEST_CONTRACT,
    LIVE_INTERACTIONS as LIVE_INTERACTIONS,
    LiveExecutionAuthorizationManifest as LiveExecutionAuthorizationManifest,
    LiveMvpPreflightDecision as LiveMvpPreflightDecision,
    LiveMvpPreflightInputs as LiveMvpPreflightInputs,
    TwoSecurityContractProof as TwoSecurityContractProof,
    evaluate_live_mvp_preflight as evaluate_live_mvp_preflight,
    prove_two_security_shared_contract as prove_two_security_shared_contract,
)
