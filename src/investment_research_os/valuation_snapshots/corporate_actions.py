from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from investment_research_os.evidence_bundles import EvidenceBundle
from investment_research_os.ids import stable_id
from investment_research_os.valuation_snapshots import (
    CapitalStructureInput,
    CorporateActionReconciliation,
    MarketSession,
    PriceObservation,
    ValuationSourceReference,
)
from investment_research_os.valuation_snapshots.composite import CorporateActionInput
from investment_research_os.valuation_snapshots.massive import (
    MassiveSplitEvent,
    MassiveSplitWindowClient,
    MassiveValuationError,
)


class MassivePersonalResearchCorporateActionAdapter:
    """Reconciles unadjusted close and filing share bases using split evidence."""

    def __init__(
        self,
        *,
        client: MassiveSplitWindowClient,
        lookback_days: int = 370,
    ) -> None:
        if lookback_days < 366:
            raise ValueError("corporate action lookback must cover at least one year")
        self.client = client
        self.lookback_days = lookback_days

    def reconcile(
        self,
        bundle: EvidenceBundle,
        session: MarketSession,
        prices: tuple[PriceObservation, ...],
        capital: CapitalStructureInput,
    ) -> CorporateActionInput:
        price = self._validated_price(bundle, session, prices)
        earliest_share_date = min(
            capital.basic_shares_effective_at,
            capital.fully_diluted_shares_effective_at,
        ).date()
        start_date = earliest_share_date - timedelta(days=self.lookback_days)
        evidence = self.client.fetch_split_window(
            bundle.security_identity.symbol,
            start_date,
            session.session_date,
        )
        if (
            evidence.ticker != bundle.security_identity.symbol
            or evidence.start_date != start_date
            or evidence.end_date != session.session_date
        ):
            raise MassiveValuationError(
                "Massive split window identity does not match reconciliation request"
            )

        reconciliation = self._reconcile_events(
            bundle,
            price,
            capital,
            evidence.events,
        )
        source_reference_id = stable_id(
            bundle.operator_id,
            "personal-corporate-action-source",
            (
                f"{bundle.security_id}:{start_date.isoformat()}:"
                f"{session.session_date.isoformat()}:massive-splits"
            ),
        )
        return CorporateActionInput(
            reconciliation=reconciliation,
            source_references=(
                ValuationSourceReference(
                    source_reference_id=source_reference_id,
                    source_type="personal_market_data",
                    provider=evidence.provider,
                    locator=evidence.source_reference,
                    published_at=None,
                    retrieved_at=evidence.retrieved_at,
                    effective_at=session.closes_at,
                    provider_plan_id=evidence.plan_id,
                    response_sha256=evidence.response_sha256,
                    provider_contract_status=evidence.contract_status,
                    provider_limitation_codes=evidence.limitation_codes,
                ),
            ),
        )

    @staticmethod
    def _validated_price(
        bundle: EvidenceBundle,
        session: MarketSession,
        prices: tuple[PriceObservation, ...],
    ) -> PriceObservation:
        if len(prices) != 1:
            raise MassiveValuationError(
                "Massive split reconciliation requires one closing price"
            )
        price = prices[0]
        if (
            price.session_date != session.session_date
            or price.primary_listing_exchange != session.primary_listing_exchange
            or price.corporate_action_adjustment_status != "unadjusted"
            or price.session_type != session.session_type
            or bundle.security_identity.primary_listing_exchange
            != session.primary_listing_exchange
        ):
            raise MassiveValuationError(
                "Massive split reconciliation price basis is invalid"
            )
        return price

    @staticmethod
    def _reconcile_events(
        bundle: EvidenceBundle,
        price: PriceObservation,
        capital: CapitalStructureInput,
        events: tuple[MassiveSplitEvent, ...],
    ) -> CorporateActionReconciliation:
        if not events:
            return CorporateActionReconciliation(
                event_id=None,
                action_type="none",
                effective_at=None,
                price_adjustment_status="unadjusted",
                share_count_adjustment_status="unadjusted",
                reconciliation_result="not_required",
            )

        latest = events[-1]
        latest_effective_at = _execution_timestamp(latest.execution_date)
        all_reflected = all(
            event.execution_date < capital.basic_shares_effective_at.date()
            and event.execution_date < capital.fully_diluted_shares_effective_at.date()
            for event in events
        )
        if len(events) == 1:
            event_id = latest.event_id
            action_type = (
                "stock_split"
                if latest.adjustment_type == "forward_split"
                else "reverse_split"
            )
        else:
            event_id = stable_id(
                bundle.operator_id,
                "personal-corporate-action-set",
                ":".join(event.event_id for event in events),
            )
            action_type = "other"

        return CorporateActionReconciliation(
            event_id=event_id,
            action_type=action_type,
            effective_at=latest_effective_at,
            price_adjustment_status=(
                "unadjusted"
                if price.corporate_action_adjustment_status == "unadjusted"
                else "indeterminate"
            ),
            share_count_adjustment_status=(
                "adjusted" if all_reflected else "indeterminate"
            ),
            reconciliation_result="reconciled" if all_reflected else "mismatch",
        )


def _execution_timestamp(execution_date: date) -> datetime:
    return datetime.combine(
        execution_date,
        time.min,
        tzinfo=ZoneInfo("America/New_York"),
    ).astimezone(UTC)


__all__ = ["MassivePersonalResearchCorporateActionAdapter"]
