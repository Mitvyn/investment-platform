from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol

from investment_research_os.evidence_bundles import EvidenceBundle
from investment_research_os.valuation_snapshots import (
    CapitalStructureInput,
    CorporateActionReconciliation,
    MarketCalendar,
    MarketSession,
    MaterialityAssessment,
    PriceObservation,
    ValuationInputCandidate,
    ValuationSnapshotError,
    ValuationSourceReference,
)

REQUIRED_SOURCE_RIGHTS = frozenset(
    {
        "persist_official_close_evidence",
        "authenticated_dashboard_display",
    }
)


@dataclass(frozen=True, slots=True)
class ApprovedValuationSource:
    approval_id: str
    provider_id: str
    contract_status: str
    active: bool
    effective_from: datetime
    expires_at: datetime
    granted_rights: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not self.approval_id.strip()
            or not self.provider_id.strip()
            or not self.contract_status.strip()
            or self.effective_from.tzinfo is None
            or self.effective_from.utcoffset() is None
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
            or self.expires_at <= self.effective_from
        ):
            raise ValueError("valuation source approval window is invalid")
        if len(set(self.granted_rights)) != len(self.granted_rights) or any(
            not right.strip() for right in self.granted_rights
        ):
            raise ValueError("valuation source approval rights are invalid")


@dataclass(frozen=True, slots=True)
class OfficialCloseInput:
    prices: tuple[PriceObservation, ...]
    source_references: tuple[ValuationSourceReference, ...]


@dataclass(frozen=True, slots=True)
class CapitalInput:
    capital: CapitalStructureInput
    source_references: tuple[ValuationSourceReference, ...]


@dataclass(frozen=True, slots=True)
class CorporateActionInput:
    reconciliation: CorporateActionReconciliation
    source_references: tuple[ValuationSourceReference, ...] = ()


@dataclass(frozen=True, slots=True)
class MaterialityInput:
    assessments: tuple[MaterialityAssessment, ...]
    policy_version: str


@dataclass(frozen=True, slots=True)
class FreshnessInput:
    capital: CapitalStructureInput
    policy_version: str


class ValuationSourceApprovalPort(Protocol):
    def current_approval(
        self,
        bundle: EvidenceBundle,
        session: MarketSession,
    ) -> ApprovedValuationSource: ...


class OfficialClosePort(Protocol):
    def load(
        self,
        bundle: EvidenceBundle,
        session: MarketSession,
    ) -> OfficialCloseInput: ...


class CapitalPort(Protocol):
    def load(
        self,
        bundle: EvidenceBundle,
        session: MarketSession,
    ) -> CapitalInput: ...


class CorporateActionPort(Protocol):
    def reconcile(
        self,
        bundle: EvidenceBundle,
        session: MarketSession,
        prices: tuple[PriceObservation, ...],
        capital: CapitalStructureInput,
    ) -> CorporateActionReconciliation | CorporateActionInput: ...


class MaterialityPort(Protocol):
    def assess(
        self,
        bundle: EvidenceBundle,
        session: MarketSession,
    ) -> MaterialityInput: ...


class FreshnessPort(Protocol):
    def assess(
        self,
        bundle: EvidenceBundle,
        session: MarketSession,
        capital: CapitalStructureInput,
    ) -> FreshnessInput: ...


class CompositeValuationInputSource:
    def __init__(
        self,
        *,
        provider_id: str,
        approval_port: ValuationSourceApprovalPort,
        market_calendar: MarketCalendar,
        official_close_port: OfficialClosePort,
        capital_port: CapitalPort,
        corporate_action_port: CorporateActionPort,
        materiality_port: MaterialityPort,
        freshness_port: FreshnessPort,
        valuation_policy_version: str,
        clock: Callable[[], datetime],
    ) -> None:
        self.provider_id = provider_id
        self.approval_port = approval_port
        self.market_calendar = market_calendar
        self.official_close_port = official_close_port
        self.capital_port = capital_port
        self.corporate_action_port = corporate_action_port
        self.materiality_port = materiality_port
        self.freshness_port = freshness_port
        self.valuation_policy_version = valuation_policy_version
        self.clock = clock

    def load(
        self,
        bundle: EvidenceBundle,
        session: MarketSession,
    ) -> ValuationInputCandidate:
        approval = self.approval_port.current_approval(bundle, session)
        if not approval.active:
            raise ValuationSnapshotError("valuation source approval is inactive")
        if (
            approval.contract_status != "approved"
            or approval.provider_id != self.provider_id
        ):
            raise ValuationSnapshotError("valuation source contract is not approved")
        checked_at = self.clock()
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise RuntimeError("valuation source clock must be timezone-aware")
        if checked_at < approval.effective_from:
            raise ValuationSnapshotError(
                "valuation source approval is not yet effective"
            )
        if checked_at >= approval.expires_at:
            raise ValuationSnapshotError("valuation source approval is expired")
        if not REQUIRED_SOURCE_RIGHTS.issubset(approval.granted_rights):
            raise ValuationSnapshotError("valuation source rights are incomplete")
        expected_session = self.market_calendar.latest_completed_session(
            bundle.security_identity.primary_listing_exchange,
            bundle.as_of_cutoff,
        )
        if expected_session != session:
            raise ValuationSnapshotError(
                "valuation source session does not match frozen bundle cutoff"
            )
        official_close = self.official_close_port.load(bundle, session)
        if any(price.provider != self.provider_id for price in official_close.prices):
            raise ValuationSnapshotError("official close provider is not approved")
        if any(price.market_status != "closed" for price in official_close.prices):
            raise ValuationSnapshotError("official close is not market-clearing")
        capital = self.capital_port.load(bundle, session)
        freshness = self.freshness_port.assess(bundle, session, capital.capital)
        corporate_action_result = self.corporate_action_port.reconcile(
            bundle,
            session,
            official_close.prices,
            freshness.capital,
        )
        if isinstance(corporate_action_result, CorporateActionInput):
            corporate_action = corporate_action_result.reconciliation
            corporate_action_sources = corporate_action_result.source_references
        else:
            corporate_action = corporate_action_result
            corporate_action_sources = ()
        if corporate_action.reconciliation_result not in {
            "not_required",
            "reconciled",
        }:
            raise ValuationSnapshotError("corporate action basis is not reconciled")
        materiality = self.materiality_port.assess(bundle, session)
        return ValuationInputCandidate(
            security_id=bundle.security_id,
            evidence_bundle_id=bundle.id,
            evidence_bundle_hash=bundle.content_hash,
            market_session=session,
            prices=official_close.prices,
            capital=freshness.capital,
            corporate_action=corporate_action,
            materiality_assessments=materiality.assessments,
            valuation_policy_version=self.valuation_policy_version,
            materiality_policy_version=materiality.policy_version,
            freshness_policy_version=freshness.policy_version,
            source_references=(
                *official_close.source_references,
                *capital.source_references,
                *corporate_action_sources,
            ),
        )


class PersonalResearchValuationInputSource:
    """Composes lower-assurance market price with primary capital evidence."""

    def __init__(
        self,
        *,
        market_calendar: MarketCalendar,
        close_port: OfficialClosePort,
        capital_port: CapitalPort,
        corporate_action_port: CorporateActionPort,
        materiality_port: MaterialityPort,
        freshness_port: FreshnessPort,
    ) -> None:
        self.market_calendar = market_calendar
        self.close_port = close_port
        self.capital_port = capital_port
        self.corporate_action_port = corporate_action_port
        self.materiality_port = materiality_port
        self.freshness_port = freshness_port

    def load(
        self,
        bundle: EvidenceBundle,
        session: MarketSession,
    ) -> ValuationInputCandidate:
        expected_session = self.market_calendar.latest_completed_session(
            bundle.security_identity.primary_listing_exchange,
            bundle.as_of_cutoff,
        )
        if expected_session != session:
            raise ValuationSnapshotError(
                "personal valuation session does not match frozen bundle cutoff"
            )
        close = self.close_port.load(bundle, session)
        source_by_id = {
            source.source_reference_id: source for source in close.source_references
        }
        if not close.prices or any(
            price.price_type != "verified_consolidated_end_of_day_close"
            or price.source_reference not in source_by_id
            or source_by_id[price.source_reference].source_type
            != "personal_market_data"
            or source_by_id[price.source_reference].provider != price.provider
            for price in close.prices
        ):
            raise ValuationSnapshotError(
                "personal valuation close provenance is invalid"
            )
        capital = self.capital_port.load(bundle, session)
        freshness = self.freshness_port.assess(bundle, session, capital.capital)
        corporate_action_result = self.corporate_action_port.reconcile(
            bundle,
            session,
            close.prices,
            freshness.capital,
        )
        if isinstance(corporate_action_result, CorporateActionInput):
            corporate_action = corporate_action_result.reconciliation
            corporate_action_sources = corporate_action_result.source_references
        else:
            corporate_action = corporate_action_result
            corporate_action_sources = ()
        materiality = self.materiality_port.assess(bundle, session)
        return ValuationInputCandidate(
            security_id=bundle.security_id,
            evidence_bundle_id=bundle.id,
            evidence_bundle_hash=bundle.content_hash,
            market_session=session,
            prices=close.prices,
            capital=freshness.capital,
            corporate_action=corporate_action,
            materiality_assessments=materiality.assessments,
            valuation_policy_version="personal_research_valuation_v1",
            materiality_policy_version=materiality.policy_version,
            freshness_policy_version=freshness.policy_version,
            source_references=(
                *close.source_references,
                *capital.source_references,
                *corporate_action_sources,
            ),
        )
