from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Callable, Mapping, Protocol

from investment_research_os.ids import stable_id


QUESTION_TYPE = "biotech_moonshot_catalyst_assessment"
QUESTION_TYPE_VERSION = "biotech_moonshot_catalyst_assessment.v1"
WORKFLOW_CONFIG_VERSION = "biotech-moonshot-catalyst-v1"
THESIS_CONTRACT_ID = "biotech_moonshot_catalyst_assessment"
ELIGIBILITY_POLICY_VERSION = "biotech-security-eligibility-v1"

RULE_IDS = (
    "security_identity_verified",
    "us_listing",
    "cik_match",
    "common_equity",
    "operating_company",
    "therapeutics_classification",
    "active_therapeutic_program",
    "defined_clinical_or_regulatory_catalyst",
    "required_primary_source_coverage",
)

REQUIRED_PRIMARY_SOURCE_COVERAGE = frozenset(
    {
        "sec_issuer_security",
        "required_sec_filings",
        "issuer_pipeline",
        "authoritative_trial",
        "us_regulatory",
        "financing_share_capital",
    }
)


class ResearchRunRequestError(ValueError):
    """Raised when a Research Run request fails its versioned contract."""


class ResearchRunNotFound(LookupError):
    """Raised when a run is absent or outside the operator boundary."""


@dataclass(frozen=True, slots=True)
class WorkflowConfigDefinition:
    question_type: str
    version: str
    question_type_version: str
    thesis_contract_id: str
    eligibility_policy_version: str
    active: bool


class WorkflowConfigRegistry(Protocol):
    def resolve(
        self,
        question_type: str,
        workflow_config_version: str,
    ) -> WorkflowConfigDefinition | None: ...


class FixedWorkflowConfigRegistry:
    """Pinned MVP workflow registry used until durable config loading exists."""

    def __init__(self, *, active: bool = True) -> None:
        self._config = WorkflowConfigDefinition(
            question_type=QUESTION_TYPE,
            version=WORKFLOW_CONFIG_VERSION,
            question_type_version=QUESTION_TYPE_VERSION,
            thesis_contract_id=THESIS_CONTRACT_ID,
            eligibility_policy_version=ELIGIBILITY_POLICY_VERSION,
            active=active,
        )

    def resolve(
        self,
        question_type: str,
        workflow_config_version: str,
    ) -> WorkflowConfigDefinition | None:
        if (
            question_type == self._config.question_type
            and workflow_config_version == self._config.version
        ):
            return self._config
        return None


DEFAULT_WORKFLOW_CONFIG_REGISTRY = FixedWorkflowConfigRegistry()


@dataclass(frozen=True, slots=True)
class ResearchQuestionRequest:
    question_type: str
    security_id: str
    as_of_cutoff: datetime
    workflow_config_version: str
    operator_focus: str | None

    def as_dict(self) -> dict[str, object]:
        return _wire_value(asdict(self))


@dataclass(frozen=True, slots=True)
class NormalizedResearchQuestionRequest:
    question_type: str
    question_type_version: str
    security_id: str
    as_of_cutoff: datetime
    workflow_config_version: str
    thesis_contract_id: str
    operator_focus_original: str | None
    operator_focus_normalized: str | None

    def as_dict(self) -> dict[str, object]:
        return _wire_value(asdict(self))


@dataclass(frozen=True, slots=True)
class AuthenticatedOperator:
    id: str

    def __post_init__(self) -> None:
        try:
            canonical_id = str(uuid.UUID(self.id))
        except (AttributeError, TypeError, ValueError) as error:
            raise ResearchRunRequestError("operator identity must be a UUID") from error
        object.__setattr__(self, "id", canonical_id)


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    evidence_id: str
    available_at: datetime


@dataclass(frozen=True, slots=True)
class CatalystCandidate:
    event: str
    program: str
    basis: str
    window_start: str
    window_end: str


@dataclass(frozen=True, slots=True)
class SecurityIdentity:
    id: str
    cik: str
    issuer_name: str
    symbol: str
    primary_listing_exchange: str


@dataclass(frozen=True, slots=True)
class SecurityEligibilitySnapshot:
    security_id: str
    as_of_cutoff: datetime
    issuer_name: str
    display_symbol: str
    security_identity_verified: bool
    primary_listing_country: str
    primary_listing_exchange: str
    cik: str
    cik_matches_issuer: bool
    security_type: str
    issuer_status: str
    therapeutics_classification: str
    active_therapeutic_programs: tuple[str, ...]
    catalysts: tuple[CatalystCandidate, ...]
    primary_source_coverage: frozenset[str]
    evidence_by_rule: Mapping[str, EvidenceReference]


@dataclass(frozen=True, slots=True)
class EligibilityCheck:
    rule_id: str
    rule_version: str
    passed: bool
    evidence_reference: str | None
    reason_code: str
    explanation: str
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    policy_version: str
    eligible: bool
    checks: tuple[EligibilityCheck, ...]
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class ResearchRun:
    id: str
    operator_id: str
    security_id: str
    security_identity: SecurityIdentity
    question_type: str
    question_type_version: str
    workflow_config_version: str
    thesis_contract_id: str
    as_of_cutoff: datetime
    operator_focus_original: str | None
    operator_focus_normalized: str | None
    status: str
    idempotency_key: str
    eligibility: EligibilityResult
    created_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": "research_run.v1",
            **_wire_value(asdict(self)),
        }


def _wire_value(value: object):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _wire_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_wire_value(item) for item in value]
    return value


class SecurityEligibilitySource(Protocol):
    def load(
        self,
        operator_id: str,
        security_id: str,
        as_of_cutoff: datetime,
    ) -> SecurityEligibilitySnapshot: ...


class ResearchRunRepository(Protocol):
    def save(self, run: ResearchRun) -> ResearchRun: ...

    def get(self, operator_id: str, run_id: str) -> ResearchRun | None: ...


class InMemoryResearchRunRepository:
    """Offline persistence boundary for tests and local workflow development."""

    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], ResearchRun] = {}

    def save(self, run: ResearchRun) -> ResearchRun:
        self._runs.setdefault((run.operator_id, run.id), run)
        return self._runs[(run.operator_id, run.id)]

    def get(self, operator_id: str, run_id: str) -> ResearchRun | None:
        return self._runs.get((operator_id, run_id))


def _normalized_focus(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ResearchRunRequestError("operator_focus must be text")
    if len(value) > 2_000:
        raise ResearchRunRequestError("operator_focus exceeds 2000 characters")
    normalized = re.sub(r"\s+", " ", value).strip()
    controlled_change_patterns = (
        r"\b(?:add|remove|skip|disable|replace)\b.{0,40}\bgraders?\b",
        r"\b(?:override|bypass|weaken|change|ignore)\b.{0,40}"
        r"\b(?:readiness|gate|eligibility|rubric|schema|workflow|disposition|"
        r"evidence requirements?)\b",
    )
    if any(
        re.search(pattern, normalized, flags=re.IGNORECASE)
        for pattern in controlled_change_patterns
    ):
        raise ResearchRunRequestError("operator_focus cannot alter workflow behavior")
    return normalized or None


def _parse_cutoff(value: object) -> datetime:
    if not isinstance(value, str):
        raise ResearchRunRequestError("as_of_cutoff must be an ISO 8601 timestamp")
    try:
        cutoff = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ResearchRunRequestError(
            "as_of_cutoff must be an ISO 8601 timestamp"
        ) from error
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ResearchRunRequestError("as_of_cutoff must include a timezone")
    return cutoff.astimezone(UTC)


def _resolve_workflow_config(
    question_type: str,
    workflow_config_version: str,
    registry: WorkflowConfigRegistry | None,
) -> WorkflowConfigDefinition:
    selected_registry = registry or DEFAULT_WORKFLOW_CONFIG_REGISTRY
    config = selected_registry.resolve(question_type, workflow_config_version)
    if config is None or not config.active:
        raise ResearchRunRequestError("workflow configuration is unavailable")
    return config


def parse_research_question_request(
    payload: Mapping[str, object],
    *,
    workflow_config_registry: WorkflowConfigRegistry | None = None,
) -> ResearchQuestionRequest:
    required_fields = {
        "question_type",
        "security_id",
        "as_of_cutoff",
        "workflow_config_version",
    }
    allowed_fields = required_fields | {"operator_focus"}
    missing_fields = sorted(required_fields - payload.keys())
    unknown_fields = sorted(payload.keys() - allowed_fields)
    if missing_fields:
        raise ResearchRunRequestError(
            f"missing required fields: {', '.join(missing_fields)}"
        )
    if unknown_fields:
        raise ResearchRunRequestError(f"unknown fields: {', '.join(unknown_fields)}")

    question_type = payload["question_type"]
    workflow_version = payload["workflow_config_version"]
    security_id = payload["security_id"]
    if question_type != QUESTION_TYPE:
        raise ResearchRunRequestError("unsupported question_type")
    config = _resolve_workflow_config(
        str(question_type),
        str(workflow_version),
        workflow_config_registry,
    )
    if not isinstance(security_id, str):
        raise ResearchRunRequestError("security_id must be a UUID")
    try:
        canonical_security_id = str(uuid.UUID(security_id))
    except ValueError as error:
        raise ResearchRunRequestError("security_id must be a UUID") from error
    focus = payload.get("operator_focus")
    if focus is not None and not isinstance(focus, str):
        raise ResearchRunRequestError("operator_focus must be text")

    return ResearchQuestionRequest(
        question_type=config.question_type,
        security_id=canonical_security_id,
        as_of_cutoff=_parse_cutoff(payload["as_of_cutoff"]),
        workflow_config_version=config.version,
        operator_focus=focus,
    )


def normalize_research_question_request(
    request: ResearchQuestionRequest,
    *,
    workflow_config_registry: WorkflowConfigRegistry | None = None,
) -> NormalizedResearchQuestionRequest:
    config = _resolve_workflow_config(
        request.question_type,
        request.workflow_config_version,
        workflow_config_registry,
    )
    return NormalizedResearchQuestionRequest(
        question_type=config.question_type,
        question_type_version=config.question_type_version,
        security_id=request.security_id,
        as_of_cutoff=request.as_of_cutoff,
        workflow_config_version=config.version,
        thesis_contract_id=config.thesis_contract_id,
        operator_focus_original=request.operator_focus,
        operator_focus_normalized=_normalized_focus(request.operator_focus),
    )


def _has_defined_catalyst(
    snapshot: SecurityEligibilitySnapshot,
    cutoff: datetime,
) -> bool:
    for catalyst in snapshot.catalysts:
        try:
            window_start = date.fromisoformat(catalyst.window_start)
            window_end = date.fromisoformat(catalyst.window_end)
        except ValueError:
            continue
        if (
            catalyst.event.strip()
            and catalyst.program.strip()
            and catalyst.basis in {"clinical", "regulatory"}
            and window_start <= window_end
            and window_end >= cutoff.date()
        ):
            return True
    return False


def _eligibility_predicates(
    snapshot: SecurityEligibilitySnapshot,
    cutoff: datetime,
) -> dict[str, bool]:
    return {
        "security_identity_verified": snapshot.security_identity_verified,
        "us_listing": (
            snapshot.primary_listing_country == "US"
            and bool(snapshot.primary_listing_exchange.strip())
        ),
        "cik_match": (
            snapshot.cik_matches_issuer and bool(re.fullmatch(r"\d{10}", snapshot.cik))
        ),
        "common_equity": snapshot.security_type == "common_equity",
        "operating_company": snapshot.issuer_status == "operating",
        "therapeutics_classification": snapshot.therapeutics_classification
        in {"therapeutics_biotech", "therapeutics_biopharma"},
        "active_therapeutic_program": any(
            program.strip() for program in snapshot.active_therapeutic_programs
        ),
        "defined_clinical_or_regulatory_catalyst": _has_defined_catalyst(
            snapshot,
            cutoff,
        ),
        "required_primary_source_coverage": REQUIRED_PRIMARY_SOURCE_COVERAGE
        <= snapshot.primary_source_coverage,
    }


def _rule_failure_reason(
    snapshot: SecurityEligibilitySnapshot,
    rule_id: str,
) -> tuple[str, str]:
    if rule_id == "security_identity_verified":
        return "security_identity_unverified", "Stable security identity is unverified."
    if rule_id == "us_listing":
        return "excluded_not_us_listed", "Security lacks a verified primary US listing."
    if rule_id == "cik_match":
        return "cik_mismatch_or_unverified", "Verified CIK does not match issuer."
    if rule_id == "common_equity":
        if snapshot.security_type == "adr":
            return "excluded_adr", "ADRs are outside this workflow."
        if snapshot.security_type in {"etf", "fund"}:
            return "excluded_fund", "Funds are outside this workflow."
        if snapshot.security_type == "private_security":
            return (
                "excluded_private_security",
                "Private securities are outside this workflow.",
            )
        return (
            "excluded_non_common_security",
            "Security is not eligible common equity.",
        )
    if rule_id == "operating_company":
        return (
            "excluded_non_operating_company",
            "Issuer is not a verified operating company.",
        )
    if rule_id == "therapeutics_classification":
        reasons = {
            "diagnostics_only": (
                "excluded_diagnostics_only",
                "Diagnostics-only issuers are outside this workflow.",
            ),
            "medical_device_only": (
                "excluded_medical_device_only",
                "Medical-device-only issuers are outside this workflow.",
            ),
            "service_provider_without_proprietary_pipeline": (
                "excluded_non_proprietary_service_provider",
                "Service providers without a proprietary therapeutic pipeline are excluded.",
            ),
        }
        return reasons.get(
            snapshot.therapeutics_classification,
            (
                "excluded_non_therapeutics_issuer",
                "Issuer is not a therapeutics biotech or biopharma company.",
            ),
        )
    if rule_id == "active_therapeutic_program":
        return (
            "no_active_therapeutic_program",
            "No active drug or biologic program is supported.",
        )
    if rule_id == "defined_clinical_or_regulatory_catalyst":
        return (
            "no_identifiable_clinical_or_regulatory_catalyst",
            "No defined clinical or regulatory catalyst is supported.",
        )
    return (
        "missing_required_primary_source_coverage",
        "Required primary-source coverage is incomplete.",
    )


def _evaluate_eligibility(
    snapshot: SecurityEligibilitySnapshot,
    *,
    cutoff: datetime,
    evaluated_at: datetime,
    policy_version: str,
) -> EligibilityResult:
    predicates = _eligibility_predicates(snapshot, cutoff)
    checks: list[EligibilityCheck] = []
    for rule_id in RULE_IDS:
        reference = snapshot.evidence_by_rule.get(rule_id)
        evidence_valid = reference is not None and reference.available_at <= cutoff
        passed = predicates[rule_id] and evidence_valid
        if passed:
            reason_code = "eligible"
            explanation = "Rule passed using evidence valid at cutoff."
        elif reference is None:
            reason_code = "missing_rule_evidence"
            explanation = "Required rule evidence is unavailable."
        elif reference.available_at > cutoff:
            reason_code = "evidence_after_cutoff"
            explanation = "Supporting evidence was not available at cutoff."
        else:
            reason_code, explanation = _rule_failure_reason(snapshot, rule_id)
        checks.append(
            EligibilityCheck(
                rule_id=rule_id,
                rule_version=f"{rule_id}.v1",
                passed=passed,
                evidence_reference=(reference.evidence_id if reference else None),
                reason_code=reason_code,
                explanation=explanation,
                evaluated_at=evaluated_at,
            )
        )
    return EligibilityResult(
        policy_version=policy_version,
        eligible=all(check.passed for check in checks),
        checks=tuple(checks),
        evaluated_at=evaluated_at,
    )


class ResearchRunWorkflow:
    def __init__(
        self,
        *,
        repository: ResearchRunRepository,
        eligibility_source: SecurityEligibilitySource,
        clock: Callable[[], datetime],
        workflow_config_registry: WorkflowConfigRegistry | None = None,
    ) -> None:
        self._repository = repository
        self._eligibility_source = eligibility_source
        self._clock = clock
        self._workflow_config_registry = (
            workflow_config_registry or DEFAULT_WORKFLOW_CONFIG_REGISTRY
        )

    def create(
        self,
        operator: AuthenticatedOperator,
        payload: Mapping[str, object],
    ) -> ResearchRun:
        request = parse_research_question_request(
            payload,
            workflow_config_registry=self._workflow_config_registry,
        )
        normalized = normalize_research_question_request(
            request,
            workflow_config_registry=self._workflow_config_registry,
        )
        config = _resolve_workflow_config(
            normalized.question_type,
            normalized.workflow_config_version,
            self._workflow_config_registry,
        )
        security_id = normalized.security_id
        cutoff = normalized.as_of_cutoff
        identity = {
            "operator_id": operator.id,
            "security_id": security_id,
            "question_type_version": normalized.question_type_version,
            "workflow_config_version": normalized.workflow_config_version,
            "as_of_cutoff": cutoff.isoformat(),
            "operator_focus": normalized.operator_focus_normalized,
        }
        idempotency_key = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        run_id = stable_id(operator.id, "committee-research-run", idempotency_key)
        existing = self._repository.get(operator.id, run_id)
        if existing is not None:
            return existing

        evaluated_at = self._clock()
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise RuntimeError("workflow clock must return a timezone-aware timestamp")
        if cutoff > evaluated_at:
            raise ResearchRunRequestError("as_of_cutoff cannot be in the future")
        snapshot = self._eligibility_source.load(operator.id, security_id, cutoff)
        if snapshot.security_id != security_id:
            raise ResearchRunRequestError("security evidence identity mismatch")
        if snapshot.as_of_cutoff != cutoff:
            raise ResearchRunRequestError("eligibility snapshot cutoff mismatch")
        eligibility = _evaluate_eligibility(
            snapshot,
            cutoff=cutoff,
            evaluated_at=evaluated_at,
            policy_version=config.eligibility_policy_version,
        )
        run = ResearchRun(
            id=run_id,
            operator_id=operator.id,
            security_id=security_id,
            security_identity=SecurityIdentity(
                id=security_id,
                cik=snapshot.cik,
                issuer_name=snapshot.issuer_name,
                symbol=snapshot.display_symbol,
                primary_listing_exchange=snapshot.primary_listing_exchange,
            ),
            question_type=QUESTION_TYPE,
            question_type_version=normalized.question_type_version,
            workflow_config_version=normalized.workflow_config_version,
            thesis_contract_id=normalized.thesis_contract_id,
            as_of_cutoff=cutoff,
            operator_focus_original=normalized.operator_focus_original,
            operator_focus_normalized=normalized.operator_focus_normalized,
            status="eligibility_evaluated",
            idempotency_key=idempotency_key,
            eligibility=eligibility,
            created_at=evaluated_at,
        )
        return self._repository.save(run)

    def get(self, operator: AuthenticatedOperator, run_id: str) -> ResearchRun:
        run = self._repository.get(operator.id, run_id)
        if run is None:
            raise ResearchRunNotFound("research run not found")
        return run


__all__ = [
    "AuthenticatedOperator",
    "CatalystCandidate",
    "EligibilityCheck",
    "EligibilityResult",
    "EvidenceReference",
    "FixedWorkflowConfigRegistry",
    "InMemoryResearchRunRepository",
    "NormalizedResearchQuestionRequest",
    "ResearchQuestionRequest",
    "ResearchRun",
    "ResearchRunNotFound",
    "ResearchRunRequestError",
    "ResearchRunWorkflow",
    "SecurityIdentity",
    "SecurityEligibilitySnapshot",
    "WorkflowConfigDefinition",
    "WorkflowConfigRegistry",
    "normalize_research_question_request",
    "parse_research_question_request",
]
