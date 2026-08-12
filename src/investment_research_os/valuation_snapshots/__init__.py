from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Callable, Protocol

from investment_research_os.evidence_bundles import (
    EvidenceBundle,
    EvidenceBundleNotFound,
    EvidenceBundleRepository,
)
from investment_research_os.ids import stable_id
from investment_research_os.research_runs import AuthenticatedOperator


class ValuationSnapshotError(ValueError):
    """Raised when valuation inputs cannot satisfy snapshot contract."""


class ValuationSnapshotNotFound(LookupError):
    """Raised when snapshot is absent or outside operator boundary."""


_ENTERPRISE_CLAIM_COMPONENT_IDS = frozenset(
    {
        "redeemable_preferred_claim",
        "noncontrolling_interest_claim",
        "royalty_monetization_liability",
        "contingent_consideration_claim",
        "pension_underfunded_claim",
        "finance_lease_claim",
    }
)
_ENTERPRISE_CLAIMS_POLICY_VERSION = "biotech-other-enterprise-claims-v1"


@dataclass(frozen=True, slots=True)
class MarketSession:
    session_date: date
    opens_at: datetime
    closes_at: datetime
    session_type: str
    primary_listing_exchange: str
    early_close: bool
    calendar_version: str


@dataclass(frozen=True, slots=True)
class PriceObservation:
    price_type: str
    session_type: str
    session_date: date
    primary_listing_exchange: str
    price: str
    currency: str
    official_close_timestamp: datetime
    market_status: str
    corporate_action_adjustment_status: str
    provider: str
    source_reference: str
    halt_verification_status: str = "verified_not_halted"


@dataclass(frozen=True, slots=True)
class DilutionInstrument:
    instrument_id: str
    instrument_type: str
    diluted_share_increment: str
    effective_at: datetime
    supporting_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EnterpriseClaimComponent:
    component_id: str
    value: str
    unit: str
    period_end: date
    effective_at: datetime
    resolution: str
    reason_code: str
    source_concept: str | None
    supporting_evidence_ids: tuple[str, ...]
    policy_version: str = "biotech-other-enterprise-claims-v1"


@dataclass(frozen=True, slots=True)
class CapitalStructureInput:
    basic_shares_outstanding: str
    fully_diluted_shares: str
    cash: str
    restricted_cash: str
    restricted_cash_treatment: str
    debt: str
    other_enterprise_claims: str
    included_cash: str
    currency: str
    basic_shares_effective_at: datetime
    fully_diluted_shares_effective_at: datetime
    cash_effective_at: datetime
    restricted_cash_effective_at: datetime
    included_cash_effective_at: datetime
    debt_effective_at: datetime
    other_enterprise_claims_effective_at: datetime
    basic_shares_evidence_ids: tuple[str, ...]
    diluted_shares_evidence_ids: tuple[str, ...]
    cash_evidence_ids: tuple[str, ...]
    restricted_cash_evidence_ids: tuple[str, ...]
    debt_evidence_ids: tuple[str, ...]
    other_enterprise_claims_evidence_ids: tuple[str, ...]
    basic_shares_freshness_state: str = "current"
    basic_shares_freshness_reason_code: str = "current_at_cutoff"
    diluted_shares_freshness_state: str = "current"
    diluted_shares_freshness_reason_code: str = "current_at_cutoff"
    cash_freshness_state: str = "current"
    cash_freshness_reason_code: str = "current_at_cutoff"
    restricted_cash_freshness_state: str = "current"
    restricted_cash_freshness_reason_code: str = "current_at_cutoff"
    debt_freshness_state: str = "current"
    debt_freshness_reason_code: str = "current_at_cutoff"
    other_enterprise_claims_freshness_state: str = "current"
    other_enterprise_claims_freshness_reason_code: str = "current_at_cutoff"
    freshness_policy_version: str = "biotech-valuation-freshness-v1"
    dilution_instruments: tuple[DilutionInstrument, ...] = ()
    other_enterprise_claim_components: tuple[EnterpriseClaimComponent, ...] = ()


@dataclass(frozen=True, slots=True)
class CorporateActionReconciliation:
    event_id: str | None
    action_type: str
    effective_at: datetime | None
    price_adjustment_status: str
    share_count_adjustment_status: str
    reconciliation_result: str


@dataclass(frozen=True, slots=True)
class MaterialityAssessment:
    evidence_id: str
    publication_at: datetime | None
    market_materiality: str
    materiality_reason_code: str
    affected_domains: tuple[str, ...]
    policy_version: str
    timing_state: str | None = None


@dataclass(frozen=True, slots=True)
class ValuationSourceReference:
    source_reference_id: str
    source_type: str
    provider: str
    locator: str
    published_at: datetime | None
    retrieved_at: datetime
    effective_at: datetime | None
    provider_plan_id: str | None = None
    response_sha256: str | None = None
    provider_contract_status: str | None = None
    provider_limitation_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ValuationAssurance:
    level: str
    usage_scope: str
    rights_assurance: str
    limitation_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValuationContract:
    contract_version: str
    price_type: str
    missing_price_reason_code: str
    snapshot_id_namespace: str
    required_policy_version: str | None
    assurance: ValuationAssurance | None


STRICT_VALUATION_CONTRACT = ValuationContract(
    contract_version="valuation_snapshot.v2",
    price_type="official_unadjusted_close",
    missing_price_reason_code="official_close_unavailable",
    snapshot_id_namespace="valuation-snapshot",
    required_policy_version=None,
    assurance=None,
)

PERSONAL_RESEARCH_VALUATION_CONTRACT = ValuationContract(
    contract_version="valuation_snapshot.personal_research.v2",
    price_type="verified_consolidated_end_of_day_close",
    missing_price_reason_code="consolidated_close_unavailable",
    snapshot_id_namespace="personal-research-valuation-snapshot",
    required_policy_version="personal_research_valuation_v2",
    assurance=ValuationAssurance(
        level="personal_research",
        usage_scope="private_personal_research",
        rights_assurance="not_independently_verified",
        limitation_codes=(
            "not_primary_venue_official_close",
            "not_institutional_grade",
            "not_for_trade_execution",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class DerivedValuation:
    value: str
    unit: str
    formula: str
    formula_version: str
    input_ids: tuple[str, ...]
    calculation_id: str
    supporting_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValuationInputCandidate:
    security_id: str
    evidence_bundle_id: str
    evidence_bundle_hash: str
    market_session: MarketSession
    prices: tuple[PriceObservation, ...]
    capital: CapitalStructureInput
    corporate_action: CorporateActionReconciliation
    materiality_assessments: tuple[MaterialityAssessment, ...]
    valuation_policy_version: str
    materiality_policy_version: str
    freshness_policy_version: str = "biotech-valuation-freshness-v1"
    source_references: tuple[ValuationSourceReference, ...] = ()


@dataclass(frozen=True, slots=True)
class ValuationSnapshot:
    id: str
    operator_id: str
    research_run_id: str
    evidence_bundle_id: str
    evidence_bundle_hash: str
    security_id: str
    as_of_cutoff: datetime
    price: PriceObservation | None
    session: MarketSession
    capital: CapitalStructureInput
    market_capitalization: DerivedValuation | None
    enterprise_value: DerivedValuation | None
    calculation_ids: tuple[str, ...]
    corporate_action: CorporateActionReconciliation
    materiality_assessments: tuple[MaterialityAssessment, ...]
    source_references: tuple[ValuationSourceReference, ...]
    snapshot_status: str
    invalid_reason_codes: tuple[str, ...]
    price_information_state: str
    market_relative_analysis_permitted: bool
    valuation_policy_version: str
    freshness_policy_version: str
    materiality_policy_version: str
    created_at: datetime
    contract_version: str = "valuation_snapshot.v2"
    valuation_assurance: ValuationAssurance | None = None

    def as_dict(self) -> dict[str, object]:
        return _snapshot_wire(self)


class MarketCalendar(Protocol):
    def latest_completed_session(
        self,
        primary_listing_exchange: str,
        cutoff: datetime,
    ) -> MarketSession: ...


class ValuationInputSource(Protocol):
    def load(
        self,
        bundle: EvidenceBundle,
        session: MarketSession,
    ) -> ValuationInputCandidate: ...


class ValuationSnapshotRepository(Protocol):
    def save(self, snapshot: ValuationSnapshot) -> ValuationSnapshot: ...

    def get(
        self,
        operator_id: str,
        snapshot_id: str,
    ) -> ValuationSnapshot | None: ...

    def get_for_run(
        self,
        operator_id: str,
        research_run_id: str,
    ) -> ValuationSnapshot | None: ...


class InMemoryValuationSnapshotRepository:
    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, str], ValuationSnapshot] = {}
        self._snapshot_ids_by_run: dict[tuple[str, str], str] = {}

    def save(self, snapshot: ValuationSnapshot) -> ValuationSnapshot:
        key = (snapshot.operator_id, snapshot.id)
        existing = self._snapshots.get(key)
        if existing is not None:
            if existing != snapshot:
                raise ValuationSnapshotError("conflicting immutable valuation snapshot")
            return existing
        run_key = (snapshot.operator_id, snapshot.research_run_id)
        existing_id = self._snapshot_ids_by_run.get(run_key)
        if existing_id is not None and existing_id != snapshot.id:
            raise ValuationSnapshotError(
                "research run already has immutable valuation snapshot"
            )
        self._snapshots[key] = snapshot
        self._snapshot_ids_by_run[run_key] = snapshot.id
        return snapshot

    def get(
        self,
        operator_id: str,
        snapshot_id: str,
    ) -> ValuationSnapshot | None:
        return self._snapshots.get((operator_id, snapshot_id))

    def get_for_run(
        self,
        operator_id: str,
        research_run_id: str,
    ) -> ValuationSnapshot | None:
        snapshot_id = self._snapshot_ids_by_run.get((operator_id, research_run_id))
        if snapshot_id is None:
            return None
        return self.get(operator_id, snapshot_id)


class ValuationSnapshotWorkflow:
    def __init__(
        self,
        *,
        evidence_bundle_repository: EvidenceBundleRepository,
        valuation_snapshot_repository: ValuationSnapshotRepository,
        market_calendar: MarketCalendar,
        input_source: ValuationInputSource,
        clock: Callable[[], datetime],
        _contract: ValuationContract = STRICT_VALUATION_CONTRACT,
    ) -> None:
        self._evidence_bundle_repository = evidence_bundle_repository
        self._valuation_snapshot_repository = valuation_snapshot_repository
        self._market_calendar = market_calendar
        self._input_source = input_source
        self._clock = clock
        self._contract = _contract

    def materialize(
        self,
        operator: AuthenticatedOperator,
        evidence_bundle_id: str,
    ) -> ValuationSnapshot:
        bundle = self._evidence_bundle_repository.get(
            operator.id,
            evidence_bundle_id,
        )
        if bundle is None:
            raise EvidenceBundleNotFound("evidence bundle not found")
        existing = self._valuation_snapshot_repository.get_for_run(
            operator.id,
            bundle.research_run_id,
        )
        if existing is not None:
            return existing
        if not bundle.grader_ready:
            raise ValuationSnapshotError(
                "valuation snapshot requires grader-ready evidence bundle"
            )

        session = self._market_calendar.latest_completed_session(
            bundle.security_identity.primary_listing_exchange,
            bundle.as_of_cutoff,
        )
        if (
            session.session_type != "regular_us_trading_session"
            or session.primary_listing_exchange
            != bundle.security_identity.primary_listing_exchange
            or session.opens_at.tzinfo is None
            or session.closes_at.tzinfo is None
            or session.opens_at >= session.closes_at
            or session.closes_at > bundle.as_of_cutoff
        ):
            raise ValuationSnapshotError("calendar returned incomplete session")
        candidate = self._input_source.load(
            bundle,
            session,
        )
        _validate_candidate(candidate, bundle, session)
        if (
            self._contract.required_policy_version is not None
            and candidate.valuation_policy_version
            != self._contract.required_policy_version
        ):
            raise ValuationSnapshotError("valuation policy does not match contract")
        if self._contract.assurance is not None:
            _validate_personal_contract_candidate(candidate)
        materiality_assessments, price_information_state = _align_materiality(
            candidate.materiality_assessments,
            session.closes_at,
            bundle.as_of_cutoff,
        )
        candidate = replace(
            candidate,
            materiality_assessments=materiality_assessments,
        )
        matches = tuple(
            observation
            for observation in candidate.prices
            if observation.price_type == self._contract.price_type
            and observation.session_type == "regular_us_trading_session"
            and observation.session_date == session.session_date
            and observation.primary_listing_exchange == session.primary_listing_exchange
            and observation.official_close_timestamp == session.closes_at
        )
        created_at = self._clock()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise RuntimeError("valuation clock must return timezone-aware timestamp")
        if len(matches) != 1:
            candidate = replace(
                candidate,
                materiality_assessments=tuple(
                    replace(assessment, timing_state="indeterminate")
                    for assessment in candidate.materiality_assessments
                ),
            )
            return self._valuation_snapshot_repository.save(
                _invalid_snapshot(
                    operator.id,
                    bundle,
                    candidate,
                    session,
                    None,
                    self._contract.missing_price_reason_code,
                    "indeterminate",
                    created_at,
                    self._contract,
                )
            )
        if matches[0].currency != candidate.capital.currency:
            return self._valuation_snapshot_repository.save(
                _invalid_snapshot(
                    operator.id,
                    bundle,
                    candidate,
                    session,
                    matches[0],
                    "currency_mismatch",
                    price_information_state,
                    created_at,
                    self._contract,
                )
            )
        if candidate.corporate_action.reconciliation_result not in {
            "reconciled",
            "not_required",
        }:
            reason = (
                "corporate_action_mismatch"
                if candidate.corporate_action.reconciliation_result == "mismatch"
                else "corporate_action_unresolved"
            )
            return self._valuation_snapshot_repository.save(
                _invalid_snapshot(
                    operator.id,
                    bundle,
                    candidate,
                    session,
                    matches[0],
                    reason,
                    price_information_state,
                    created_at,
                    self._contract,
                )
            )
        if matches[0].corporate_action_adjustment_status != "unadjusted":
            return self._valuation_snapshot_repository.save(
                _invalid_snapshot(
                    operator.id,
                    bundle,
                    candidate,
                    session,
                    matches[0],
                    "price_adjustment_status_invalid",
                    price_information_state,
                    created_at,
                    self._contract,
                )
            )
        if (
            self._contract.assurance is not None
            and matches[0].halt_verification_status != "verified_not_halted"
        ):
            market_reason = (
                "market_halted"
                if matches[0].halt_verification_status == "halted"
                else "market_halt_status_indeterminate"
            )
            return self._valuation_snapshot_repository.save(
                _invalid_snapshot(
                    operator.id,
                    bundle,
                    candidate,
                    session,
                    matches[0],
                    market_reason,
                    price_information_state,
                    created_at,
                    self._contract,
                )
            )
        if matches[0].market_status != "closed":
            market_reason = (
                "market_halt_status_indeterminate"
                if matches[0].market_status == "indeterminate"
                else "market_halted"
            )
            return self._valuation_snapshot_repository.save(
                _invalid_snapshot(
                    operator.id,
                    bundle,
                    candidate,
                    session,
                    matches[0],
                    market_reason,
                    price_information_state,
                    created_at,
                    self._contract,
                )
            )
        freshness_states = (
            candidate.capital.basic_shares_freshness_state,
            candidate.capital.diluted_shares_freshness_state,
            candidate.capital.cash_freshness_state,
            candidate.capital.restricted_cash_freshness_state,
            candidate.capital.debt_freshness_state,
            candidate.capital.other_enterprise_claims_freshness_state,
        )
        if any(state != "current" for state in freshness_states):
            reason = (
                "stale_capital_input"
                if "stale" in freshness_states
                else "indeterminate_capital_input"
            )
            return self._valuation_snapshot_repository.save(
                _invalid_snapshot(
                    operator.id,
                    bundle,
                    candidate,
                    session,
                    matches[0],
                    reason,
                    price_information_state,
                    created_at,
                    self._contract,
                )
            )
        expected_diluted_shares = _decimal(
            candidate.capital.basic_shares_outstanding,
            "basic shares outstanding",
        ) + sum(
            (
                _decimal(
                    instrument.diluted_share_increment,
                    "dilution instrument increment",
                )
                for instrument in candidate.capital.dilution_instruments
            ),
            start=Decimal(0),
        )
        if expected_diluted_shares != _decimal(
            candidate.capital.fully_diluted_shares,
            "fully diluted shares",
        ):
            return self._valuation_snapshot_repository.save(
                _invalid_snapshot(
                    operator.id,
                    bundle,
                    candidate,
                    session,
                    matches[0],
                    "diluted_share_reconciliation_mismatch",
                    price_information_state,
                    created_at,
                    self._contract,
                )
            )
        market_capitalization, enterprise_value = _calculate_values(
            operator.id,
            bundle.id,
            matches[0],
            candidate.capital,
        )
        snapshot = ValuationSnapshot(
            id=stable_id(
                operator.id,
                self._contract.snapshot_id_namespace,
                bundle.id,
            ),
            operator_id=operator.id,
            research_run_id=bundle.research_run_id,
            evidence_bundle_id=bundle.id,
            evidence_bundle_hash=bundle.content_hash,
            security_id=bundle.security_id,
            as_of_cutoff=bundle.as_of_cutoff,
            price=matches[0],
            session=session,
            capital=candidate.capital,
            market_capitalization=market_capitalization,
            enterprise_value=enterprise_value,
            calculation_ids=(
                _fully_diluted_calculation_id(operator.id, bundle.id),
                market_capitalization.calculation_id,
                enterprise_value.calculation_id,
            ),
            corporate_action=candidate.corporate_action,
            materiality_assessments=candidate.materiality_assessments,
            source_references=candidate.source_references,
            snapshot_status="valid",
            invalid_reason_codes=(),
            price_information_state=price_information_state,
            market_relative_analysis_permitted=(price_information_state == "aligned"),
            valuation_policy_version=candidate.valuation_policy_version,
            freshness_policy_version=candidate.freshness_policy_version,
            materiality_policy_version=candidate.materiality_policy_version,
            created_at=created_at,
            contract_version=self._contract.contract_version,
            valuation_assurance=self._contract.assurance,
        )
        return self._valuation_snapshot_repository.save(snapshot)


class PersonalResearchValuationSnapshotWorkflow(ValuationSnapshotWorkflow):
    def __init__(
        self,
        *,
        evidence_bundle_repository: EvidenceBundleRepository,
        valuation_snapshot_repository: ValuationSnapshotRepository,
        market_calendar: MarketCalendar,
        input_source: ValuationInputSource,
        clock: Callable[[], datetime],
    ) -> None:
        super().__init__(
            evidence_bundle_repository=evidence_bundle_repository,
            valuation_snapshot_repository=valuation_snapshot_repository,
            market_calendar=market_calendar,
            input_source=input_source,
            clock=clock,
            _contract=PERSONAL_RESEARCH_VALUATION_CONTRACT,
        )


def _align_materiality(
    assessments: tuple[MaterialityAssessment, ...],
    official_close_timestamp: datetime,
    cutoff: datetime,
) -> tuple[tuple[MaterialityAssessment, ...], str]:
    normalized: list[MaterialityAssessment] = []
    for assessment in assessments:
        if assessment.publication_at is None:
            timing_state = "indeterminate"
        elif assessment.publication_at > cutoff:
            raise ValuationSnapshotError(
                "materiality evidence publication occurs after cutoff"
            )
        elif assessment.publication_at <= official_close_timestamp:
            timing_state = "before_or_at_close"
        else:
            timing_state = "after_close_before_or_at_cutoff"
        normalized.append(replace(assessment, timing_state=timing_state))

    if any(
        assessment.timing_state == "indeterminate"
        or assessment.market_materiality == "indeterminate"
        for assessment in normalized
    ):
        state = "indeterminate"
    elif any(
        assessment.timing_state == "after_close_before_or_at_cutoff"
        and assessment.market_materiality == "material"
        for assessment in normalized
    ):
        state = "pre_material_evidence"
    else:
        state = "aligned"
    return tuple(normalized), state


def _validate_candidate(
    candidate: ValuationInputCandidate,
    bundle: EvidenceBundle,
    session: MarketSession,
) -> None:
    if (
        candidate.security_id != bundle.security_id
        or candidate.evidence_bundle_id != bundle.id
        or candidate.evidence_bundle_hash != bundle.content_hash
        or candidate.market_session != session
    ):
        raise ValuationSnapshotError("valuation candidate identity mismatch")
    capital = candidate.capital
    if not re.fullmatch(r"[A-Z]{3}", capital.currency):
        raise ValuationSnapshotError("invalid valuation currency")
    for value, label in (
        (capital.basic_shares_outstanding, "basic shares outstanding"),
        (capital.fully_diluted_shares, "fully diluted shares"),
        (capital.cash, "cash"),
        (capital.restricted_cash, "restricted cash"),
        (capital.debt, "debt"),
        (capital.other_enterprise_claims, "other enterprise claims"),
        (capital.included_cash, "included cash"),
    ):
        _decimal(value, label)
    effective_timestamps = (
        capital.basic_shares_effective_at,
        capital.fully_diluted_shares_effective_at,
        capital.cash_effective_at,
        capital.restricted_cash_effective_at,
        capital.included_cash_effective_at,
        capital.debt_effective_at,
        capital.other_enterprise_claims_effective_at,
    )
    if any(
        value.tzinfo is None or value.utcoffset() is None or value > bundle.as_of_cutoff
        for value in effective_timestamps
    ):
        raise ValuationSnapshotError("capital input timestamp is invalid")
    cash = _decimal(capital.cash, "cash")
    restricted_cash = _decimal(capital.restricted_cash, "restricted cash")
    included_cash = _decimal(capital.included_cash, "included cash")
    if (
        len(
            {
                capital.cash_effective_at,
                capital.restricted_cash_effective_at,
                capital.included_cash_effective_at,
            }
        )
        != 1
    ):
        raise ValuationSnapshotError("restricted cash effective time mismatch")
    if capital.restricted_cash_treatment == "none":
        expected_included_cash = cash
        valid_restricted_cash = restricted_cash == 0
    elif capital.restricted_cash_treatment == "included":
        expected_included_cash = cash
        valid_restricted_cash = restricted_cash <= cash
    elif capital.restricted_cash_treatment == "excluded":
        expected_included_cash = cash - restricted_cash
        valid_restricted_cash = restricted_cash <= cash
    else:
        raise ValuationSnapshotError("restricted cash treatment is invalid")
    if not valid_restricted_cash or included_cash != expected_included_cash:
        raise ValuationSnapshotError("restricted cash reconciliation mismatch")
    claim_components = capital.other_enterprise_claim_components
    component_ids = [component.component_id for component in claim_components]
    if (
        len(component_ids) != len(_ENTERPRISE_CLAIM_COMPONENT_IDS)
        or set(component_ids) != _ENTERPRISE_CLAIM_COMPONENT_IDS
    ):
        raise ValuationSnapshotError(
            "other enterprise claim component vector is incomplete"
        )
    claim_total = Decimal(0)
    for component in claim_components:
        value = _decimal(
            component.value,
            f"other enterprise claim {component.component_id}",
        )
        if (
            component.unit != capital.currency
            or component.period_end
            != capital.other_enterprise_claims_effective_at.date()
            or component.effective_at.tzinfo is None
            or component.effective_at.utcoffset() is None
            or component.effective_at.date() != component.period_end
            or component.effective_at > bundle.as_of_cutoff
            or component.resolution
            not in {
                "reported",
                "tagged_zero",
                "explicit_negation",
                "structural_absence",
            }
            or component.policy_version != _ENTERPRISE_CLAIMS_POLICY_VERSION
            or not component.supporting_evidence_ids
        ):
            raise ValuationSnapshotError(
                f"other enterprise claim component is invalid:{component.component_id}"
            )
        claim_total += value
    if claim_total != _decimal(
        capital.other_enterprise_claims,
        "other enterprise claims",
    ):
        raise ValuationSnapshotError("other enterprise claim total mismatch")
    if candidate.freshness_policy_version != capital.freshness_policy_version:
        raise ValuationSnapshotError("freshness policy mismatch")

    evidence_ids = {item.evidence_id for item in bundle.manifest}
    materiality_ids = [
        assessment.evidence_id for assessment in candidate.materiality_assessments
    ]
    if (
        len(materiality_ids) != len(set(materiality_ids))
        or set(materiality_ids) != evidence_ids
    ):
        raise ValuationSnapshotError(
            "materiality assessments must cover bundle evidence exactly"
        )
    for assessment in candidate.materiality_assessments:
        if assessment.policy_version != candidate.materiality_policy_version:
            raise ValuationSnapshotError("materiality policy mismatch")

    source_ids = {source.source_reference_id for source in candidate.source_references}
    if len(source_ids) != len(candidate.source_references):
        raise ValuationSnapshotError("duplicate valuation source reference")
    for price in candidate.prices:
        _decimal(price.price, "share price")
        if price.halt_verification_status not in {
            "verified_not_halted",
            "halted",
            "indeterminate",
        }:
            raise ValuationSnapshotError("invalid halt verification status")
        if price.source_reference not in source_ids:
            raise ValuationSnapshotError("unresolved price source reference")
        if (
            price.corporate_action_adjustment_status
            != candidate.corporate_action.price_adjustment_status
        ):
            raise ValuationSnapshotError(
                "price and corporate action adjustment mismatch"
            )
    for instrument in capital.dilution_instruments:
        _decimal(
            instrument.diluted_share_increment,
            "dilution instrument increment",
        )
        if instrument.effective_at > bundle.as_of_cutoff:
            raise ValuationSnapshotError("dilution instrument occurs after cutoff")

    required_evidence_groups = (
        capital.basic_shares_evidence_ids,
        capital.diluted_shares_evidence_ids,
        capital.cash_evidence_ids,
        capital.restricted_cash_evidence_ids,
        capital.debt_evidence_ids,
        capital.other_enterprise_claims_evidence_ids,
        *(
            instrument.supporting_evidence_ids
            for instrument in capital.dilution_instruments
        ),
        *(
            component.supporting_evidence_ids
            for component in capital.other_enterprise_claim_components
        ),
    )
    if any(not evidence_ids for evidence_ids in required_evidence_groups):
        raise ValuationSnapshotError("capital input evidence is incomplete")
    supported_evidence = (
        *capital.basic_shares_evidence_ids,
        *capital.diluted_shares_evidence_ids,
        *capital.cash_evidence_ids,
        *capital.restricted_cash_evidence_ids,
        *capital.debt_evidence_ids,
        *capital.other_enterprise_claims_evidence_ids,
        *(
            evidence_id
            for instrument in capital.dilution_instruments
            for evidence_id in instrument.supporting_evidence_ids
        ),
        *(
            evidence_id
            for component in capital.other_enterprise_claim_components
            for evidence_id in component.supporting_evidence_ids
        ),
    )
    if any(evidence_id not in evidence_ids for evidence_id in supported_evidence):
        raise ValuationSnapshotError("unresolved valuation evidence")


def _validate_personal_contract_candidate(
    candidate: ValuationInputCandidate,
) -> None:
    sources = {
        source.source_reference_id: source for source in candidate.source_references
    }
    for price in candidate.prices:
        if price.price_type != PERSONAL_RESEARCH_VALUATION_CONTRACT.price_type:
            continue
        source = sources[price.source_reference]
        if (
            source.source_type != "personal_market_data"
            or source.provider_plan_id is None
            or not source.provider_plan_id.strip()
            or source.response_sha256 is None
            or re.fullmatch(r"[0-9a-f]{64}", source.response_sha256) is None
            or source.provider_contract_status is None
            or not source.provider_contract_status.strip()
            or not source.provider_limitation_codes
            or len(set(source.provider_limitation_codes))
            != len(source.provider_limitation_codes)
            or any(
                re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code) is None
                for code in source.provider_limitation_codes
            )
        ):
            raise ValuationSnapshotError(
                "personal market source provenance is incomplete"
            )
    for source in candidate.source_references:
        if source.source_type not in {"personal_market_data", "primary_filing"}:
            raise ValuationSnapshotError("personal valuation source type is invalid")
        if source.source_type == "primary_filing" and (
            source.provider_plan_id is not None
            or source.response_sha256 is not None
            or source.provider_contract_status is not None
            or source.provider_limitation_codes
        ):
            raise ValuationSnapshotError(
                "primary filing cannot carry market provider provenance"
            )


def _invalid_snapshot(
    operator_id: str,
    bundle: EvidenceBundle,
    candidate: ValuationInputCandidate,
    session: MarketSession,
    price: PriceObservation | None,
    reason: str,
    price_information_state: str,
    created_at: datetime,
    contract: ValuationContract,
) -> ValuationSnapshot:
    calculation_ids = (
        ()
        if reason == "diluted_share_reconciliation_mismatch"
        else (_fully_diluted_calculation_id(operator_id, bundle.id),)
    )
    return ValuationSnapshot(
        id=stable_id(operator_id, contract.snapshot_id_namespace, bundle.id),
        operator_id=operator_id,
        research_run_id=bundle.research_run_id,
        evidence_bundle_id=bundle.id,
        evidence_bundle_hash=bundle.content_hash,
        security_id=bundle.security_id,
        as_of_cutoff=bundle.as_of_cutoff,
        price=price,
        session=session,
        capital=candidate.capital,
        market_capitalization=None,
        enterprise_value=None,
        calculation_ids=calculation_ids,
        corporate_action=candidate.corporate_action,
        materiality_assessments=candidate.materiality_assessments,
        source_references=candidate.source_references,
        snapshot_status="invalid",
        invalid_reason_codes=(reason,),
        price_information_state=price_information_state,
        market_relative_analysis_permitted=False,
        valuation_policy_version=candidate.valuation_policy_version,
        freshness_policy_version=candidate.freshness_policy_version,
        materiality_policy_version=candidate.materiality_policy_version,
        created_at=created_at,
        contract_version=contract.contract_version,
        valuation_assurance=contract.assurance,
    )


def _fully_diluted_calculation_id(
    operator_id: str,
    evidence_bundle_id: str,
) -> str:
    return stable_id(
        operator_id,
        "valuation-calculation",
        f"{evidence_bundle_id}:fully_diluted_shares:v1",
    )


def _input_id(snapshot: ValuationSnapshot, input_name: str) -> str:
    return stable_id(
        snapshot.operator_id,
        "valuation-input",
        f"{snapshot.evidence_bundle_id}:{input_name}",
    )


def _capital_measure_wire(
    snapshot: ValuationSnapshot,
    input_name: str,
    value: str,
    unit: str,
    effective_at: datetime,
    evidence_ids: tuple[str, ...],
    freshness_state: str,
    freshness_reason_code: str,
    *,
    calculated: bool = False,
) -> dict[str, object]:
    capital = snapshot.capital
    calculation_id = (
        _fully_diluted_calculation_id(
            snapshot.operator_id,
            snapshot.evidence_bundle_id,
        )
        if calculated
        else None
    )
    return {
        "input_id": _input_id(snapshot, input_name),
        "value": value,
        "unit": unit,
        "effective_at": effective_at.isoformat(),
        "calculation_method": "calculated" if calculated else "reported",
        "formula": (
            "basic shares outstanding + dilution instruments" if calculated else None
        ),
        "calculation_id": calculation_id,
        "input_ids": (
            [
                _input_id(snapshot, "basic_shares_outstanding"),
                *[
                    instrument.instrument_id
                    for instrument in capital.dilution_instruments
                ],
            ]
            if calculated
            else []
        ),
        "supporting_evidence_ids": list(evidence_ids),
        "freshness_state": freshness_state,
        "freshness_reason_code": freshness_reason_code,
        "freshness_policy_version": capital.freshness_policy_version,
    }


def _derived_wire(value: DerivedValuation | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "value": value.value,
        "unit": value.unit,
        "formula": value.formula,
        "formula_version": value.formula_version,
        "input_ids": list(value.input_ids),
        "calculation_id": value.calculation_id,
        "supporting_evidence_ids": list(value.supporting_evidence_ids),
    }


def _snapshot_wire(snapshot: ValuationSnapshot) -> dict[str, object]:
    price = snapshot.price
    if price is None:
        price_basis = None
    else:
        price_basis = {
            "input_id": _input_id(snapshot, "share_price"),
            "price_type": price.price_type,
            "session_type": price.session_type,
            "session_date": price.session_date.isoformat(),
            "primary_listing_exchange": price.primary_listing_exchange,
            "share_price": price.price,
            "market_calendar_version": snapshot.session.calendar_version,
            "market_status": price.market_status,
            "corporate_action_adjustment_status": (
                price.corporate_action_adjustment_status
            ),
            "provider_source_reference_id": price.source_reference,
        }
        if snapshot.valuation_assurance is None:
            price_basis["official_close_timestamp"] = (
                price.official_close_timestamp.isoformat()
            )
        else:
            price_basis["price_timestamp"] = price.official_close_timestamp.isoformat()
            price_basis["timestamp_basis"] = "market_calendar_session_close"
            price_basis["halt_verification_status"] = price.halt_verification_status
    capital = snapshot.capital
    evidence_ids = tuple(
        dict.fromkeys(
            assessment.evidence_id for assessment in snapshot.materiality_assessments
        )
    )
    wire = {
        "contract_version": snapshot.contract_version,
        "id": snapshot.id,
        "operator_id": snapshot.operator_id,
        "research_run_id": snapshot.research_run_id,
        "evidence_bundle_id": snapshot.evidence_bundle_id,
        "evidence_bundle_hash": snapshot.evidence_bundle_hash,
        "security_id": snapshot.security_id,
        "as_of_cutoff": snapshot.as_of_cutoff.isoformat(),
        "snapshot_status": snapshot.snapshot_status,
        "invalid_reason_codes": list(snapshot.invalid_reason_codes),
        "currency": capital.currency,
        "price_basis": price_basis,
        "basic_shares_outstanding": _capital_measure_wire(
            snapshot,
            "basic_shares_outstanding",
            capital.basic_shares_outstanding,
            "shares",
            capital.basic_shares_effective_at,
            capital.basic_shares_evidence_ids,
            capital.basic_shares_freshness_state,
            capital.basic_shares_freshness_reason_code,
        ),
        "dilution_instruments": [
            {
                "instrument_id": instrument.instrument_id,
                "instrument_type": instrument.instrument_type,
                "diluted_share_increment": instrument.diluted_share_increment,
                "effective_at": instrument.effective_at.isoformat(),
                "supporting_evidence_ids": list(instrument.supporting_evidence_ids),
            }
            for instrument in capital.dilution_instruments
        ],
        "fully_diluted_shares": _capital_measure_wire(
            snapshot,
            "fully_diluted_shares",
            capital.fully_diluted_shares,
            "shares",
            capital.fully_diluted_shares_effective_at,
            capital.diluted_shares_evidence_ids,
            capital.diluted_shares_freshness_state,
            capital.diluted_shares_freshness_reason_code,
            calculated=(
                _fully_diluted_calculation_id(
                    snapshot.operator_id,
                    snapshot.evidence_bundle_id,
                )
                in snapshot.calculation_ids
            ),
        ),
        "cash": _capital_measure_wire(
            snapshot,
            "included_cash",
            capital.included_cash,
            capital.currency,
            capital.included_cash_effective_at,
            capital.cash_evidence_ids,
            capital.cash_freshness_state,
            capital.cash_freshness_reason_code,
        ),
        "debt": _capital_measure_wire(
            snapshot,
            "included_debt",
            capital.debt,
            capital.currency,
            capital.debt_effective_at,
            capital.debt_evidence_ids,
            capital.debt_freshness_state,
            capital.debt_freshness_reason_code,
        ),
        "cash_treatment": {
            "reported_cash": _capital_measure_wire(
                snapshot,
                "reported_cash",
                capital.cash,
                capital.currency,
                capital.cash_effective_at,
                capital.cash_evidence_ids,
                capital.cash_freshness_state,
                capital.cash_freshness_reason_code,
            ),
            "restricted_cash": _capital_measure_wire(
                snapshot,
                "restricted_cash",
                capital.restricted_cash,
                capital.currency,
                capital.restricted_cash_effective_at,
                capital.restricted_cash_evidence_ids,
                capital.restricted_cash_freshness_state,
                capital.restricted_cash_freshness_reason_code,
            ),
            "restricted_cash_treatment": (capital.restricted_cash_treatment),
        },
        "other_enterprise_claims": _capital_measure_wire(
            snapshot,
            "other_enterprise_claims",
            capital.other_enterprise_claims,
            capital.currency,
            capital.other_enterprise_claims_effective_at,
            capital.other_enterprise_claims_evidence_ids,
            capital.other_enterprise_claims_freshness_state,
            capital.other_enterprise_claims_freshness_reason_code,
        ),
        "other_enterprise_claim_components": [
            {
                "component_id": component.component_id,
                "value": component.value,
                "unit": component.unit,
                "period_end": component.period_end.isoformat(),
                "effective_at": component.effective_at.isoformat(),
                "resolution": component.resolution,
                "reason_code": component.reason_code,
                "source_concept": component.source_concept,
                "supporting_evidence_ids": list(
                    component.supporting_evidence_ids
                ),
                "policy_version": component.policy_version,
            }
            for component in capital.other_enterprise_claim_components
        ],
        "market_capitalization": _derived_wire(snapshot.market_capitalization),
        "enterprise_value": _derived_wire(snapshot.enterprise_value),
        "source_references": [
            {
                "source_reference_id": source.source_reference_id,
                "source_type": source.source_type,
                "provider": source.provider,
                "locator": source.locator,
                "published_at": (
                    source.published_at.isoformat()
                    if source.published_at is not None
                    else None
                ),
                "retrieved_at": source.retrieved_at.isoformat(),
                "effective_at": (
                    source.effective_at.isoformat()
                    if source.effective_at is not None
                    else None
                ),
                **(
                    {
                        "provider_plan_id": source.provider_plan_id,
                        "response_sha256": source.response_sha256,
                        "provider_contract_status": (
                            source.provider_contract_status
                        ),
                        "provider_limitation_codes": list(
                            source.provider_limitation_codes
                        ),
                    }
                    if snapshot.valuation_assurance is not None
                    else {
                        **(
                            {"provider_plan_id": source.provider_plan_id}
                            if source.provider_plan_id is not None
                            else {}
                        ),
                        **(
                            {"response_sha256": source.response_sha256}
                            if source.response_sha256 is not None
                            else {}
                        ),
                    }
                ),
            }
            for source in snapshot.source_references
        ],
        "evidence_ids": list(evidence_ids),
        "calculation_ids": list(snapshot.calculation_ids),
        "corporate_action_reconciliation": {
            "event_id": snapshot.corporate_action.event_id,
            "event_type": snapshot.corporate_action.action_type,
            "effective_at": (
                snapshot.corporate_action.effective_at.isoformat()
                if snapshot.corporate_action.effective_at is not None
                else None
            ),
            "price_adjustment_status": (
                snapshot.corporate_action.price_adjustment_status
            ),
            "share_count_adjustment_status": (
                snapshot.corporate_action.share_count_adjustment_status
            ),
            "reconciliation_result": (snapshot.corporate_action.reconciliation_result),
        },
        "evidence_materiality": [
            {
                "evidence_id": assessment.evidence_id,
                "publication_at": (
                    assessment.publication_at.isoformat()
                    if assessment.publication_at is not None
                    else None
                ),
                "timing_state": assessment.timing_state,
                "market_materiality": assessment.market_materiality,
                "materiality_reason_code": (assessment.materiality_reason_code),
                "materiality_policy_version": assessment.policy_version,
                "affected_domains": list(assessment.affected_domains),
            }
            for assessment in snapshot.materiality_assessments
        ],
        "price_information_state": snapshot.price_information_state,
        "market_relative_analysis_permitted": (
            snapshot.market_relative_analysis_permitted
        ),
        "price_basis_policy_version": snapshot.valuation_policy_version,
        "freshness_policy_version": snapshot.freshness_policy_version,
        "materiality_policy_version": snapshot.materiality_policy_version,
        "created_at": snapshot.created_at.isoformat(),
    }
    if snapshot.valuation_assurance is not None:
        wire["valuation_assurance"] = {
            "level": snapshot.valuation_assurance.level,
            "usage_scope": snapshot.valuation_assurance.usage_scope,
            "rights_assurance": snapshot.valuation_assurance.rights_assurance,
            "limitation_codes": list(snapshot.valuation_assurance.limitation_codes),
        }
    return wire


def _decimal(value: str, label: str) -> Decimal:
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
        raise ValuationSnapshotError(f"invalid {label}")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValuationSnapshotError(f"invalid {label}") from error
    if not parsed.is_finite() or parsed < 0:
        raise ValuationSnapshotError(f"invalid {label}")
    return parsed


def _calculate_values(
    operator_id: str,
    evidence_bundle_id: str,
    price: PriceObservation,
    capital: CapitalStructureInput,
) -> tuple[DerivedValuation, DerivedValuation]:
    share_price = _decimal(price.price, "share price")
    fully_diluted_shares = _decimal(
        capital.fully_diluted_shares,
        "fully diluted shares",
    )
    debt = _decimal(capital.debt, "debt")
    other_enterprise_claims = _decimal(
        capital.other_enterprise_claims,
        "other enterprise claims",
    )
    included_cash = _decimal(capital.included_cash, "included cash")
    market_cap_value = share_price * fully_diluted_shares
    enterprise_value = market_cap_value + debt + other_enterprise_claims - included_cash
    if enterprise_value < 0:
        raise ValuationSnapshotError("enterprise value cannot be negative")

    price_input_id = stable_id(
        operator_id,
        "valuation-input",
        f"{evidence_bundle_id}:share_price",
    )
    fully_diluted_shares_input_id = stable_id(
        operator_id,
        "valuation-input",
        f"{evidence_bundle_id}:fully_diluted_shares",
    )
    debt_input_id = stable_id(
        operator_id,
        "valuation-input",
        f"{evidence_bundle_id}:included_debt",
    )
    other_claims_input_id = stable_id(
        operator_id,
        "valuation-input",
        f"{evidence_bundle_id}:other_enterprise_claims",
    )
    cash_input_id = stable_id(
        operator_id,
        "valuation-input",
        f"{evidence_bundle_id}:included_cash",
    )
    market_cap_id = stable_id(
        operator_id,
        "valuation-calculation",
        f"{evidence_bundle_id}:market_capitalization:valuation-formulas-v1",
    )
    enterprise_value_id = stable_id(
        operator_id,
        "valuation-calculation",
        f"{evidence_bundle_id}:enterprise_value:valuation-formulas-v2",
    )
    market_capitalization = DerivedValuation(
        value=format(market_cap_value, "f"),
        unit=capital.currency,
        formula="share_price * fully_diluted_shares",
        formula_version="market-capitalization-v1",
        input_ids=(price_input_id, fully_diluted_shares_input_id),
        calculation_id=market_cap_id,
        supporting_evidence_ids=capital.diluted_shares_evidence_ids,
    )
    return market_capitalization, DerivedValuation(
        value=format(enterprise_value, "f"),
        unit=capital.currency,
        formula=(
            "market_capitalization + debt + other_enterprise_claims - included_cash"
        ),
        formula_version="enterprise-value-v2",
        input_ids=(
            market_cap_id,
            debt_input_id,
            other_claims_input_id,
            cash_input_id,
        ),
        calculation_id=enterprise_value_id,
        supporting_evidence_ids=tuple(
            dict.fromkeys(
                (
                    *capital.diluted_shares_evidence_ids,
                    *capital.debt_evidence_ids,
                    *capital.other_enterprise_claims_evidence_ids,
                    *capital.cash_evidence_ids,
                )
            )
        ),
    )


__all__ = [
    "CapitalStructureInput",
    "CorporateActionReconciliation",
    "DerivedValuation",
    "DilutionInstrument",
    "EnterpriseClaimComponent",
    "InMemoryValuationSnapshotRepository",
    "MarketSession",
    "MaterialityAssessment",
    "PERSONAL_RESEARCH_VALUATION_CONTRACT",
    "PersonalResearchValuationSnapshotWorkflow",
    "PriceObservation",
    "STRICT_VALUATION_CONTRACT",
    "ValuationAssurance",
    "ValuationContract",
    "ValuationInputCandidate",
    "ValuationSnapshot",
    "ValuationSnapshotError",
    "ValuationSnapshotNotFound",
    "ValuationSnapshotWorkflow",
    "ValuationSourceReference",
]
