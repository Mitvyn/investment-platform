from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
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


@dataclass(frozen=True, slots=True)
class DilutionInstrument:
    instrument_id: str
    instrument_type: str
    diluted_share_increment: str
    effective_at: datetime
    supporting_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CapitalStructureInput:
    basic_shares_outstanding: str
    fully_diluted_shares: str
    cash: str
    debt: str
    other_included_claims: str
    included_cash: str
    currency: str
    effective_date: date
    basic_shares_evidence_ids: tuple[str, ...]
    diluted_shares_evidence_ids: tuple[str, ...]
    cash_evidence_ids: tuple[str, ...]
    debt_evidence_ids: tuple[str, ...]
    basic_shares_freshness_state: str = "current"
    basic_shares_freshness_reason_code: str = "current_at_cutoff"
    diluted_shares_freshness_state: str = "current"
    diluted_shares_freshness_reason_code: str = "current_at_cutoff"
    cash_freshness_state: str = "current"
    cash_freshness_reason_code: str = "current_at_cutoff"
    debt_freshness_state: str = "current"
    debt_freshness_reason_code: str = "current_at_cutoff"
    freshness_policy_version: str = "biotech-valuation-freshness-v1"
    dilution_instruments: tuple[DilutionInstrument, ...] = ()


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
        security_id: str,
        cutoff: datetime,
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
                raise ValuationSnapshotError(
                    "conflicting immutable valuation snapshot"
                )
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
        snapshot_id = self._snapshot_ids_by_run.get(
            (operator_id, research_run_id)
        )
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
    ) -> None:
        self._evidence_bundle_repository = evidence_bundle_repository
        self._valuation_snapshot_repository = valuation_snapshot_repository
        self._market_calendar = market_calendar
        self._input_source = input_source
        self._clock = clock

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
            bundle.security_id,
            bundle.as_of_cutoff,
        )
        _validate_candidate(candidate, bundle)
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
            if observation.price_type == "official_unadjusted_close"
            and observation.session_type == "regular_us_trading_session"
            and observation.session_date == session.session_date
            and observation.primary_listing_exchange
            == session.primary_listing_exchange
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
                    "official_close_unavailable",
                    "indeterminate",
                    created_at,
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
                )
            )
        if matches[0].market_status != "closed":
            return self._valuation_snapshot_repository.save(
                _invalid_snapshot(
                    operator.id,
                    bundle,
                    candidate,
                    session,
                    matches[0],
                    "market_halted",
                    price_information_state,
                    created_at,
                )
            )
        freshness_states = (
            candidate.capital.basic_shares_freshness_state,
            candidate.capital.diluted_shares_freshness_state,
            candidate.capital.cash_freshness_state,
            candidate.capital.debt_freshness_state,
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
                "valuation-snapshot",
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
            market_relative_analysis_permitted=(
                price_information_state == "aligned"
            ),
            valuation_policy_version=candidate.valuation_policy_version,
            freshness_policy_version=candidate.freshness_policy_version,
            materiality_policy_version=candidate.materiality_policy_version,
            created_at=created_at,
        )
        return self._valuation_snapshot_repository.save(snapshot)


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
) -> None:
    capital = candidate.capital
    if not re.fullmatch(r"[A-Z]{3}", capital.currency):
        raise ValuationSnapshotError("invalid valuation currency")
    for value, label in (
        (capital.basic_shares_outstanding, "basic shares outstanding"),
        (capital.fully_diluted_shares, "fully diluted shares"),
        (capital.cash, "cash"),
        (capital.debt, "debt"),
        (capital.other_included_claims, "other included claims"),
        (capital.included_cash, "included cash"),
    ):
        _decimal(value, label)
    if capital.effective_date > bundle.as_of_cutoff.date():
        raise ValuationSnapshotError("capital input occurs after cutoff")
    if candidate.freshness_policy_version != capital.freshness_policy_version:
        raise ValuationSnapshotError("freshness policy mismatch")

    evidence_ids = {item.evidence_id for item in bundle.manifest}
    materiality_ids = [
        assessment.evidence_id
        for assessment in candidate.materiality_assessments
    ]
    if len(materiality_ids) != len(set(materiality_ids)) or set(
        materiality_ids
    ) != evidence_ids:
        raise ValuationSnapshotError(
            "materiality assessments must cover bundle evidence exactly"
        )
    for assessment in candidate.materiality_assessments:
        if assessment.policy_version != candidate.materiality_policy_version:
            raise ValuationSnapshotError("materiality policy mismatch")

    source_ids = {
        source.source_reference_id for source in candidate.source_references
    }
    if len(source_ids) != len(candidate.source_references):
        raise ValuationSnapshotError("duplicate valuation source reference")
    for price in candidate.prices:
        _decimal(price.price, "share price")
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
            raise ValuationSnapshotError(
                "dilution instrument occurs after cutoff"
            )

    supported_evidence = (
        *capital.basic_shares_evidence_ids,
        *capital.diluted_shares_evidence_ids,
        *capital.cash_evidence_ids,
        *capital.debt_evidence_ids,
        *(
            evidence_id
            for instrument in capital.dilution_instruments
            for evidence_id in instrument.supporting_evidence_ids
        ),
    )
    if any(evidence_id not in evidence_ids for evidence_id in supported_evidence):
        raise ValuationSnapshotError("unresolved valuation evidence")


def _invalid_snapshot(
    operator_id: str,
    bundle: EvidenceBundle,
    candidate: ValuationInputCandidate,
    session: MarketSession,
    price: PriceObservation | None,
    reason: str,
    price_information_state: str,
    created_at: datetime,
) -> ValuationSnapshot:
    calculation_ids = (
        ()
        if reason == "diluted_share_reconciliation_mismatch"
        else (_fully_diluted_calculation_id(operator_id, bundle.id),)
    )
    return ValuationSnapshot(
        id=stable_id(operator_id, "valuation-snapshot", bundle.id),
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
        "effective_at": datetime.combine(
            capital.effective_date,
            time(23, 59, 59),
            tzinfo=UTC,
        ).isoformat(),
        "calculation_method": "calculated" if calculated else "reported",
        "formula": (
            "basic shares outstanding + dilution instruments"
            if calculated
            else None
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
    price_basis = (
        None
        if price is None
        else {
            "input_id": _input_id(snapshot, "share_price"),
            "price_type": price.price_type,
            "session_type": price.session_type,
            "session_date": price.session_date.isoformat(),
            "primary_listing_exchange": price.primary_listing_exchange,
            "share_price": price.price,
            "official_close_timestamp": price.official_close_timestamp.isoformat(),
            "market_calendar_version": snapshot.session.calendar_version,
            "market_status": price.market_status,
            "corporate_action_adjustment_status": (
                price.corporate_action_adjustment_status
            ),
            "provider_source_reference_id": price.source_reference,
        }
    )
    capital = snapshot.capital
    evidence_ids = tuple(
        dict.fromkeys(
            assessment.evidence_id
            for assessment in snapshot.materiality_assessments
        )
    )
    return {
        "contract_version": "valuation_snapshot.v1",
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
                "supporting_evidence_ids": list(
                    instrument.supporting_evidence_ids
                ),
            }
            for instrument in capital.dilution_instruments
        ],
        "fully_diluted_shares": _capital_measure_wire(
            snapshot,
            "fully_diluted_shares",
            capital.fully_diluted_shares,
            "shares",
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
            capital.cash_evidence_ids,
            capital.cash_freshness_state,
            capital.cash_freshness_reason_code,
        ),
        "debt": _capital_measure_wire(
            snapshot,
            "included_debt",
            capital.debt,
            capital.currency,
            capital.debt_evidence_ids,
            capital.debt_freshness_state,
            capital.debt_freshness_reason_code,
        ),
        "market_capitalization": _derived_wire(
            snapshot.market_capitalization
        ),
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
            "reconciliation_result": (
                snapshot.corporate_action.reconciliation_result
            ),
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
                "materiality_reason_code": (
                    assessment.materiality_reason_code
                ),
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
    included_cash = _decimal(capital.included_cash, "included cash")
    market_cap_value = share_price * fully_diluted_shares
    enterprise_value = market_cap_value + debt - included_cash
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
        f"{evidence_bundle_id}:enterprise_value:valuation-formulas-v1",
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
        formula="market_capitalization + debt - cash",
        formula_version="enterprise-value-v1",
        input_ids=(market_cap_id, debt_input_id, cash_input_id),
        calculation_id=enterprise_value_id,
        supporting_evidence_ids=tuple(
            dict.fromkeys(
                (
                    *capital.diluted_shares_evidence_ids,
                    *capital.debt_evidence_ids,
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
    "InMemoryValuationSnapshotRepository",
    "MarketSession",
    "MaterialityAssessment",
    "PriceObservation",
    "ValuationInputCandidate",
    "ValuationSnapshot",
    "ValuationSnapshotError",
    "ValuationSnapshotNotFound",
    "ValuationSnapshotWorkflow",
    "ValuationSourceReference",
]
