from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import re
from uuid import UUID


SECOND_FIXTURE_SELECTION_POLICY_VERSION = "second-live-fixture-selection.v1"
_PERSONAL_QUESTION_TYPE = "biotech_moonshot_catalyst_personal_research_assessment"
_PERSONAL_WORKFLOW_CONFIG = "biotech-moonshot-catalyst-personal-research-v1"
_PERSONAL_VALUATION_CONTRACT = "valuation_snapshot.personal_research.v2"
_REQUIRED_SOURCE_PLAN_CONTRACT = "primary_source_plan.v3"
_REQUIRED_ELIGIBILITY_POLICY = "biotech-eligibility-sources-v1"
REQUIRED_ELIGIBILITY_RULE_IDS = (
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
REQUIRED_SOURCE_COVERAGE_IDS = (
    "sec_issuer_security",
    "required_sec_filings",
    "issuer_pipeline",
    "authoritative_trial",
    "us_regulatory",
    "financing_share_capital",
)
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CLINICAL_PHASES = frozenset(
    {
        "phase_1",
        "phase_1_2",
        "phase_2",
        "phase_2_3",
        "phase_3",
        "regulatory_review",
    }
)
_CATALYST_BASES = frozenset(
    {
        "clinical_start",
        "clinical_readout",
        "regulatory_submission",
        "regulatory_decision",
    }
)
_CATALYST_HORIZONS = frozenset({"within_6_months", "6_to_12_months", "12_to_24_months"})
_FINANCING_STATES = frozenset(
    {
        "funded_through_catalyst",
        "financing_likely_before_catalyst",
        "financing_required_before_catalyst",
    }
)
_DILUTION_MECHANISMS = frozenset(
    {
        "atm",
        "shelf",
        "warrants",
        "convertibles",
        "options",
        "rsus",
        "preferreds",
        "exchangeable_shares",
        "contingent_shares",
        "none",
    }
)
_VALUATION_SCALE_BUCKETS = frozenset({"micro", "small", "mid", "large"})
_VALUATION_STATES = frozenset({"valid", "invalid"})
_PRICE_INFORMATION_STATES = frozenset(
    {"aligned", "pre_material_evidence", "indeterminate"}
)
_CORPORATE_ACTION_STATES = frozenset({"reconciled", "mismatch", "unresolved"})
_CLINICAL_DIFFERENCE_DIMENSIONS = frozenset(
    {
        "clinical_phase",
        "catalyst_basis",
        "catalyst_horizon",
        "active_study_footprint",
    }
)
_CAPITAL_DIFFERENCE_DIMENSIONS = frozenset(
    {
        "financing_before_catalyst",
        "dilution_mechanisms",
        "valuation_scale",
    }
)


class SecondFixtureSelectionError(ValueError):
    """Raised when a deterministic selection receipt cannot be produced."""


@dataclass(frozen=True, slots=True)
class ScreeningCheck:
    check_id: str
    passed: bool

    def __post_init__(self) -> None:
        if not self.check_id.strip() or not isinstance(self.passed, bool):
            raise ValueError("screening check is invalid")


@dataclass(frozen=True, slots=True)
class SecondFixtureScreeningRecord:
    security_id: str
    as_of_cutoff: datetime
    question_type: str
    workflow_config_version: str
    eligibility_policy_version: str
    eligibility_checks: tuple[ScreeningCheck, ...]
    source_coverage: tuple[ScreeningCheck, ...]
    source_plan_contract_version: str
    source_plan_hash: str
    evidence_bundle_id: str
    evidence_bundle_hash: str
    evidence_bundle_ready: bool
    blocking_gap_codes: tuple[str, ...]
    valuation_snapshot_id: str
    valuation_contract_version: str
    valuation_status: str
    price_information_state: str
    corporate_action_reconciliation_result: str
    clinical_phase_bucket: str
    catalyst_basis: str
    catalyst_horizon_bucket: str
    active_study_count: int
    financing_before_catalyst: str
    dilution_mechanisms: tuple[str, ...]
    valuation_scale_bucket: str

    def __post_init__(self) -> None:
        try:
            canonical_security_id = str(UUID(self.security_id))
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("screening security ID is invalid") from error
        object.__setattr__(self, "security_id", canonical_security_id)
        if self.as_of_cutoff.tzinfo is None or self.as_of_cutoff.utcoffset() is None:
            raise ValueError("screening cutoff must include timezone")
        object.__setattr__(self, "as_of_cutoff", self.as_of_cutoff.astimezone(UTC))
        for value, label in (
            (self.question_type, "question type"),
            (self.workflow_config_version, "workflow config"),
            (self.eligibility_policy_version, "eligibility policy"),
            (self.source_plan_contract_version, "source plan contract"),
            (self.evidence_bundle_id, "evidence bundle ID"),
            (self.valuation_snapshot_id, "valuation snapshot ID"),
            (self.valuation_contract_version, "valuation contract"),
        ):
            if not value.strip():
                raise ValueError(f"screening {label} is invalid")
        if tuple(check.check_id for check in self.eligibility_checks) != (
            REQUIRED_ELIGIBILITY_RULE_IDS
        ):
            raise ValueError("screening eligibility checks are invalid")
        if tuple(check.check_id for check in self.source_coverage) != (
            REQUIRED_SOURCE_COVERAGE_IDS
        ):
            raise ValueError("screening source coverage is invalid")
        if not _HASH_PATTERN.fullmatch(
            self.source_plan_hash
        ) or not _HASH_PATTERN.fullmatch(self.evidence_bundle_hash):
            raise ValueError("screening content hash is invalid")
        if not isinstance(self.evidence_bundle_ready, bool):
            raise ValueError("screening bundle readiness is invalid")
        if (
            any(not code.strip() for code in self.blocking_gap_codes)
            or len(self.blocking_gap_codes) != len(set(self.blocking_gap_codes))
            or self.blocking_gap_codes != tuple(sorted(self.blocking_gap_codes))
        ):
            raise ValueError("screening blocking gaps are invalid")
        if self.valuation_status not in _VALUATION_STATES:
            raise ValueError("screening valuation status is invalid")
        if self.price_information_state not in _PRICE_INFORMATION_STATES:
            raise ValueError("screening price information state is invalid")
        if self.corporate_action_reconciliation_result not in _CORPORATE_ACTION_STATES:
            raise ValueError("screening corporate action state is invalid")
        if self.clinical_phase_bucket not in _CLINICAL_PHASES:
            raise ValueError("screening clinical phase is invalid")
        if self.catalyst_basis not in _CATALYST_BASES:
            raise ValueError("screening catalyst basis is invalid")
        if self.catalyst_horizon_bucket not in _CATALYST_HORIZONS:
            raise ValueError("screening catalyst horizon is invalid")
        if (
            isinstance(self.active_study_count, bool)
            or not isinstance(self.active_study_count, int)
            or self.active_study_count < 1
        ):
            raise ValueError("screening active study count is invalid")
        if self.financing_before_catalyst not in _FINANCING_STATES:
            raise ValueError("screening financing state is invalid")
        if (
            not self.dilution_mechanisms
            or any(
                item not in _DILUTION_MECHANISMS for item in self.dilution_mechanisms
            )
            or len(self.dilution_mechanisms) != len(set(self.dilution_mechanisms))
            or self.dilution_mechanisms != tuple(sorted(self.dilution_mechanisms))
            or (
                "none" in self.dilution_mechanisms
                and len(self.dilution_mechanisms) != 1
            )
        ):
            raise ValueError("screening dilution mechanisms are invalid")
        if self.valuation_scale_bucket not in _VALUATION_SCALE_BUCKETS:
            raise ValueError("screening valuation scale is invalid")


@dataclass(frozen=True, slots=True)
class CandidateSelectionOutcome:
    security_id: str
    eligible_for_selection: bool
    difference_dimensions: tuple[str, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SecondFixtureSelectionReceipt:
    policy_version: str
    reference_security_id: str
    reference_record_hash: str
    pool_hash: str
    outcomes: tuple[CandidateSelectionOutcome, ...]
    selected_security_id: str | None
    receipt_hash: str


def select_second_live_fixture(
    *,
    reference: SecondFixtureScreeningRecord,
    candidates: tuple[SecondFixtureScreeningRecord, ...],
) -> SecondFixtureSelectionReceipt:
    if not candidates:
        raise SecondFixtureSelectionError("second fixture candidate pool is empty")
    reference_reasons = _foundation_reasons(reference, reference=reference)
    if reference_reasons or (
        reference.question_type != _PERSONAL_QUESTION_TYPE
        or reference.workflow_config_version != _PERSONAL_WORKFLOW_CONFIG
        or reference.eligibility_policy_version != _REQUIRED_ELIGIBILITY_POLICY
        or reference.source_plan_contract_version != _REQUIRED_SOURCE_PLAN_CONTRACT
        or reference.valuation_contract_version != _PERSONAL_VALUATION_CONTRACT
    ):
        raise SecondFixtureSelectionError("reference fixture is not selection ready")
    candidate_ids = tuple(candidate.security_id for candidate in candidates)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise SecondFixtureSelectionError("second fixture candidate pool is ambiguous")

    ordered_candidates = tuple(sorted(candidates, key=lambda item: item.security_id))
    outcomes = tuple(
        _candidate_outcome(reference=reference, candidate=candidate)
        for candidate in ordered_candidates
    )
    selectable = tuple(
        outcome for outcome in outcomes if outcome.eligible_for_selection
    )
    selected_security_id = (
        None
        if not selectable
        else sorted(
            selectable,
            key=lambda outcome: (
                -len(outcome.difference_dimensions),
                outcome.security_id,
            ),
        )[0].security_id
    )
    pool_hash = _hash_payload(
        [_record_wire(candidate) for candidate in ordered_candidates]
    )
    reference_record_hash = _hash_payload(_record_wire(reference))
    receipt_payload = {
        "policy_version": SECOND_FIXTURE_SELECTION_POLICY_VERSION,
        "reference_security_id": reference.security_id,
        "reference_record_hash": reference_record_hash,
        "pool_hash": pool_hash,
        "outcomes": [asdict(outcome) for outcome in outcomes],
        "selected_security_id": selected_security_id,
    }
    return SecondFixtureSelectionReceipt(
        policy_version=SECOND_FIXTURE_SELECTION_POLICY_VERSION,
        reference_security_id=reference.security_id,
        reference_record_hash=reference_record_hash,
        pool_hash=pool_hash,
        outcomes=outcomes,
        selected_security_id=selected_security_id,
        receipt_hash=_hash_payload(receipt_payload),
    )


def _candidate_outcome(
    *,
    reference: SecondFixtureScreeningRecord,
    candidate: SecondFixtureScreeningRecord,
) -> CandidateSelectionOutcome:
    reasons = list(_foundation_reasons(candidate, reference=reference))
    dimensions = _difference_dimensions(reference, candidate)
    if not reasons:
        if not _CLINICAL_DIFFERENCE_DIMENSIONS.intersection(dimensions):
            reasons.append("insufficient_clinical_catalyst_difference")
        if not _CAPITAL_DIFFERENCE_DIMENSIONS.intersection(dimensions):
            reasons.append("insufficient_financing_valuation_difference")
        if len(dimensions) < 2:
            reasons.append("insufficient_total_difference")
    return CandidateSelectionOutcome(
        security_id=candidate.security_id,
        eligible_for_selection=not reasons,
        difference_dimensions=dimensions,
        reason_codes=tuple(reasons),
    )


def _foundation_reasons(
    record: SecondFixtureScreeningRecord,
    *,
    reference: SecondFixtureScreeningRecord,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if record is not reference and record.security_id == reference.security_id:
        reasons.append("reference_security")
    if record.question_type != reference.question_type:
        reasons.append("question_contract_mismatch")
    if record.workflow_config_version != reference.workflow_config_version:
        reasons.append("workflow_config_mismatch")
    if record.eligibility_policy_version != reference.eligibility_policy_version:
        reasons.append("eligibility_policy_mismatch")
    if record.as_of_cutoff != reference.as_of_cutoff:
        reasons.append("cutoff_mismatch")
    if record.source_plan_contract_version != reference.source_plan_contract_version:
        reasons.append("source_plan_contract_mismatch")
    reasons.extend(
        f"eligibility_failed:{check.check_id}"
        for check in record.eligibility_checks
        if not check.passed
    )
    reasons.extend(
        f"coverage_failed:{check.check_id}"
        for check in record.source_coverage
        if not check.passed
    )
    if not record.evidence_bundle_ready:
        reasons.append("evidence_bundle_not_ready")
    if record.blocking_gap_codes:
        reasons.append("blocking_evidence_gaps")
    if record.valuation_contract_version != reference.valuation_contract_version:
        reasons.append("valuation_contract_mismatch")
    if record.valuation_status != "valid":
        reasons.append("valuation_snapshot_invalid")
    if record.price_information_state != "aligned":
        reasons.append("price_information_not_aligned")
    if record.corporate_action_reconciliation_result != "reconciled":
        reasons.append("corporate_action_not_reconciled")
    return tuple(reasons)


def _difference_dimensions(
    reference: SecondFixtureScreeningRecord,
    candidate: SecondFixtureScreeningRecord,
) -> tuple[str, ...]:
    differences = {
        "clinical_phase": (
            reference.clinical_phase_bucket != candidate.clinical_phase_bucket
        ),
        "catalyst_basis": reference.catalyst_basis != candidate.catalyst_basis,
        "catalyst_horizon": (
            reference.catalyst_horizon_bucket != candidate.catalyst_horizon_bucket
        ),
        "active_study_footprint": (
            _study_footprint(reference.active_study_count)
            != _study_footprint(candidate.active_study_count)
        ),
        "financing_before_catalyst": (
            reference.financing_before_catalyst != candidate.financing_before_catalyst
        ),
        "dilution_mechanisms": (
            reference.dilution_mechanisms != candidate.dilution_mechanisms
        ),
        "valuation_scale": (
            reference.valuation_scale_bucket != candidate.valuation_scale_bucket
        ),
    }
    return tuple(sorted(key for key, differs in differences.items() if differs))


def _study_footprint(count: int) -> str:
    if count == 1:
        return "one"
    if count <= 3:
        return "two_to_three"
    return "four_or_more"


def _record_wire(record: SecondFixtureScreeningRecord) -> dict[str, object]:
    return {
        "security_id": record.security_id,
        "as_of_cutoff": record.as_of_cutoff.isoformat(),
        "question_type": record.question_type,
        "workflow_config_version": record.workflow_config_version,
        "eligibility_policy_version": record.eligibility_policy_version,
        "eligibility_checks": [asdict(check) for check in record.eligibility_checks],
        "source_coverage": [asdict(check) for check in record.source_coverage],
        "source_plan_contract_version": record.source_plan_contract_version,
        "source_plan_hash": record.source_plan_hash,
        "evidence_bundle_id": record.evidence_bundle_id,
        "evidence_bundle_hash": record.evidence_bundle_hash,
        "evidence_bundle_ready": record.evidence_bundle_ready,
        "blocking_gap_codes": record.blocking_gap_codes,
        "valuation_snapshot_id": record.valuation_snapshot_id,
        "valuation_contract_version": record.valuation_contract_version,
        "valuation_status": record.valuation_status,
        "price_information_state": record.price_information_state,
        "corporate_action_reconciliation_result": (
            record.corporate_action_reconciliation_result
        ),
        "clinical_phase_bucket": record.clinical_phase_bucket,
        "catalyst_basis": record.catalyst_basis,
        "catalyst_horizon_bucket": record.catalyst_horizon_bucket,
        "active_study_count": record.active_study_count,
        "financing_before_catalyst": record.financing_before_catalyst,
        "dilution_mechanisms": record.dilution_mechanisms,
        "valuation_scale_bucket": record.valuation_scale_bucket,
    }


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CandidateSelectionOutcome",
    "REQUIRED_ELIGIBILITY_RULE_IDS",
    "REQUIRED_SOURCE_COVERAGE_IDS",
    "SECOND_FIXTURE_SELECTION_POLICY_VERSION",
    "ScreeningCheck",
    "SecondFixtureScreeningRecord",
    "SecondFixtureSelectionError",
    "SecondFixtureSelectionReceipt",
    "select_second_live_fixture",
]
