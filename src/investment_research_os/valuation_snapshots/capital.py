from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from investment_research_os.evidence_bundles import (
    EvidenceBundle,
    EvidenceItem,
    VerifiedMetricSnapshot,
)
from investment_research_os.ids import stable_id
from investment_research_os.valuation_snapshots import (
    CapitalStructureInput,
    DilutionInstrument,
    MarketSession,
    ValuationSnapshotError,
    ValuationSourceReference,
)
from investment_research_os.valuation_snapshots.composite import (
    CapitalInput,
    FreshnessInput,
)


FRESHNESS_POLICY_VERSION = "biotech-valuation-freshness-v1"

_DILUTION_METRICS = (
    ("option_shares_outstanding", "stock_options"),
    ("warrant_shares_outstanding", "warrants"),
    ("convertible_share_equivalents", "convertibles"),
    ("rsu_shares_outstanding", "restricted_stock_units"),
    ("preferred_shares_outstanding", "preferred_securities"),
)
_MONETARY_METRICS = (
    "cash_and_cash_equivalents",
    "restricted_cash",
    "debt_total",
    "other_included_claims",
)
_REQUIRED_METRICS = (
    "basic_shares_outstanding",
    *tuple(key for key, _instrument_type in _DILUTION_METRICS),
    *_MONETARY_METRICS,
)


def _canonical_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _number(metric: VerifiedMetricSnapshot) -> Decimal:
    try:
        value = Decimal(metric.value)
    except InvalidOperation as error:
        raise ValuationSnapshotError(
            f"capital_metric_value_invalid:{metric.metric_key}"
        ) from error
    if not value.is_finite() or value < 0:
        raise ValuationSnapshotError(
            f"capital_metric_value_invalid:{metric.metric_key}"
        )
    if metric.unit == "shares" and value != value.to_integral_value():
        raise ValuationSnapshotError(
            f"capital_metric_value_invalid:{metric.metric_key}"
        )
    return value


def _effective_at(metric: VerifiedMetricSnapshot) -> datetime:
    if metric.period_end is None:
        raise ValuationSnapshotError(
            f"capital_metric_period_missing:{metric.metric_key}"
        )
    return datetime.combine(metric.period_end, time(23, 59, 59), tzinfo=UTC)


def _metric_map(bundle: EvidenceBundle) -> dict[str, VerifiedMetricSnapshot]:
    grouped: dict[str, list[VerifiedMetricSnapshot]] = {}
    for metric in bundle.metrics:
        if metric.metric_key in _REQUIRED_METRICS:
            grouped.setdefault(metric.metric_key, []).append(metric)
    selected: dict[str, VerifiedMetricSnapshot] = {}
    for key in _REQUIRED_METRICS:
        candidates = grouped.get(key, [])
        if not candidates:
            raise ValuationSnapshotError(f"capital_metric_missing:{key}")
        eligible = [
            metric
            for metric in candidates
            if metric.period_end is not None
            and metric.period_end <= bundle.as_of_cutoff.date()
        ]
        if not eligible:
            raise ValuationSnapshotError(f"capital_metric_period_invalid:{key}")
        latest_period = max(metric.period_end for metric in eligible)
        latest = [metric for metric in eligible if metric.period_end == latest_period]
        if len(latest) != 1:
            raise ValuationSnapshotError(f"capital_metric_ambiguous:{key}")
        selected[key] = latest[0]
    return selected


def _support_items(
    bundle: EvidenceBundle,
    metrics: dict[str, VerifiedMetricSnapshot],
) -> dict[str, EvidenceItem]:
    manifest = {item.evidence_id: item for item in bundle.manifest}
    support_ids = {
        evidence_id
        for metric in metrics.values()
        for evidence_id in metric.supporting_evidence_ids
    }
    items: dict[str, EvidenceItem] = {}
    for evidence_id in sorted(support_ids):
        item = manifest.get(evidence_id)
        if item is None:
            raise ValuationSnapshotError(f"capital_evidence_unresolved:{evidence_id}")
        hostname = (urlparse(item.canonical_url).hostname or "").casefold()
        if (
            item.provenance_type != "primary_source"
            or item.item_kind != "passage"
            or item.source_class not in {"sec", "financing"}
            or not (hostname == "sec.gov" or hostname.endswith(".sec.gov"))
        ):
            raise ValuationSnapshotError(
                f"capital_evidence_not_primary_filing:{evidence_id}"
            )
        if item.publication_at is None:
            raise ValuationSnapshotError(
                f"capital_evidence_publication_indeterminate:{evidence_id}"
            )
        if item.publication_at > bundle.as_of_cutoff:
            raise ValuationSnapshotError(f"capital_evidence_after_cutoff:{evidence_id}")
        if item.effective_at is not None and item.effective_at > bundle.as_of_cutoff:
            raise ValuationSnapshotError(
                f"capital_evidence_effective_after_cutoff:{evidence_id}"
            )
        if item.freshness == "stale":
            raise ValuationSnapshotError(f"capital_evidence_stale:{evidence_id}")
        if item.freshness != "current":
            raise ValuationSnapshotError(
                f"capital_evidence_freshness_indeterminate:{evidence_id}"
            )
        items[evidence_id] = item
    return items


def _evidence_ids(metric: VerifiedMetricSnapshot) -> tuple[str, ...]:
    return tuple(dict.fromkeys(metric.supporting_evidence_ids))


class FrozenEvidenceCapitalPort:
    """Build capital inputs only from one immutable primary-evidence bundle."""

    def load(
        self,
        bundle: EvidenceBundle,
        session: MarketSession,
    ) -> CapitalInput:
        if not bundle.grader_ready or any(gap.blocking for gap in bundle.gaps):
            raise ValuationSnapshotError("capital_evidence_bundle_not_ready")
        if session.session_date > bundle.as_of_cutoff.date():
            raise ValuationSnapshotError("capital_session_after_bundle_cutoff")

        metrics = _metric_map(bundle)
        support_items = _support_items(bundle, metrics)
        for key, metric in metrics.items():
            expected_unit = "USD" if key in _MONETARY_METRICS else "shares"
            if metric.unit != expected_unit:
                raise ValuationSnapshotError(f"capital_metric_unit_invalid:{key}")
            if not metric.supporting_evidence_ids:
                raise ValuationSnapshotError(f"capital_metric_evidence_missing:{key}")
            if metric.calculation_method == "reported":
                if metric.formula is not None:
                    raise ValuationSnapshotError(
                        f"capital_metric_formula_invalid:{key}"
                    )
            elif metric.calculation_method == "derived":
                if metric.formula is None or not metric.formula.strip():
                    raise ValuationSnapshotError(
                        f"capital_metric_formula_missing:{key}"
                    )
            else:
                raise ValuationSnapshotError(
                    f"capital_metric_calculation_method_invalid:{key}"
                )
            _number(metric)
            if _effective_at(metric) > bundle.as_of_cutoff:
                raise ValuationSnapshotError(f"capital_metric_after_cutoff:{key}")

        cash = metrics["cash_and_cash_equivalents"]
        restricted_cash = metrics["restricted_cash"]
        if cash.period_end != restricted_cash.period_end:
            raise ValuationSnapshotError("capital_cash_period_mismatch")
        cash_value = _number(cash)
        restricted_cash_value = _number(restricted_cash)
        if restricted_cash_value > cash_value:
            raise ValuationSnapshotError("capital_restricted_cash_exceeds_cash")

        basic = metrics["basic_shares_outstanding"]
        basic_value = _number(basic)
        dilution_instruments = tuple(
            DilutionInstrument(
                instrument_id=stable_id(
                    bundle.operator_id,
                    "valuation-dilution-instrument",
                    f"{bundle.id}:{key}:{metrics[key].snapshot_id}",
                ),
                instrument_type=instrument_type,
                diluted_share_increment=_canonical_decimal(_number(metrics[key])),
                effective_at=_effective_at(metrics[key]),
                supporting_evidence_ids=_evidence_ids(metrics[key]),
            )
            for key, instrument_type in _DILUTION_METRICS
        )
        fully_diluted_value = basic_value + sum(
            (
                Decimal(instrument.diluted_share_increment)
                for instrument in dilution_instruments
            ),
            Decimal(0),
        )
        diluted_evidence_ids = tuple(
            dict.fromkeys(
                (
                    *basic.supporting_evidence_ids,
                    *(
                        evidence_id
                        for instrument in dilution_instruments
                        for evidence_id in instrument.supporting_evidence_ids
                    ),
                )
            )
        )
        dilution_effective_at = max(
            _effective_at(basic),
            *(instrument.effective_at for instrument in dilution_instruments),
        )
        debt = metrics["debt_total"]
        other_claims = metrics["other_included_claims"]
        cash_effective_at = _effective_at(cash)
        current_reason = "latest_required_filing_at_cutoff"
        capital = CapitalStructureInput(
            basic_shares_outstanding=_canonical_decimal(basic_value),
            fully_diluted_shares=_canonical_decimal(fully_diluted_value),
            cash=_canonical_decimal(cash_value),
            restricted_cash=_canonical_decimal(restricted_cash_value),
            restricted_cash_treatment="excluded",
            debt=_canonical_decimal(_number(debt)),
            other_included_claims=_canonical_decimal(_number(other_claims)),
            included_cash=_canonical_decimal(cash_value - restricted_cash_value),
            currency="USD",
            basic_shares_effective_at=_effective_at(basic),
            fully_diluted_shares_effective_at=dilution_effective_at,
            cash_effective_at=cash_effective_at,
            restricted_cash_effective_at=cash_effective_at,
            included_cash_effective_at=cash_effective_at,
            debt_effective_at=_effective_at(debt),
            other_included_claims_effective_at=_effective_at(other_claims),
            basic_shares_evidence_ids=_evidence_ids(basic),
            diluted_shares_evidence_ids=diluted_evidence_ids,
            cash_evidence_ids=_evidence_ids(cash),
            restricted_cash_evidence_ids=_evidence_ids(restricted_cash),
            debt_evidence_ids=_evidence_ids(debt),
            other_included_claims_evidence_ids=_evidence_ids(other_claims),
            basic_shares_freshness_reason_code=current_reason,
            diluted_shares_freshness_reason_code=current_reason,
            cash_freshness_reason_code=current_reason,
            restricted_cash_freshness_reason_code=current_reason,
            debt_freshness_reason_code=current_reason,
            other_included_claims_freshness_reason_code=current_reason,
            freshness_policy_version=FRESHNESS_POLICY_VERSION,
            dilution_instruments=dilution_instruments,
        )
        source_references = tuple(
            ValuationSourceReference(
                source_reference_id=item.evidence_id,
                source_type="primary_filing",
                provider="sec",
                locator=item.canonical_url,
                published_at=item.publication_at,
                retrieved_at=item.retrieved_at,
                effective_at=item.effective_at,
            )
            for item in sorted(
                support_items.values(), key=lambda item: item.evidence_id
            )
        )
        return CapitalInput(capital=capital, source_references=source_references)


class FrozenEvidenceCapitalFreshnessPort:
    """Preserve only freshness already proven by frozen filing evidence."""

    def assess(
        self,
        bundle: EvidenceBundle,
        session: MarketSession,
        capital: CapitalStructureInput,
    ) -> FreshnessInput:
        if session.session_date > bundle.as_of_cutoff.date():
            raise ValuationSnapshotError("capital_session_after_bundle_cutoff")
        if capital.freshness_policy_version != FRESHNESS_POLICY_VERSION:
            raise ValuationSnapshotError("capital_freshness_policy_mismatch")
        states = (
            capital.basic_shares_freshness_state,
            capital.diluted_shares_freshness_state,
            capital.cash_freshness_state,
            capital.restricted_cash_freshness_state,
            capital.debt_freshness_state,
            capital.other_included_claims_freshness_state,
        )
        if any(state != "current" for state in states):
            raise ValuationSnapshotError("capital_freshness_not_current")
        effective_times = (
            capital.basic_shares_effective_at,
            capital.fully_diluted_shares_effective_at,
            capital.cash_effective_at,
            capital.restricted_cash_effective_at,
            capital.included_cash_effective_at,
            capital.debt_effective_at,
            capital.other_included_claims_effective_at,
        )
        if any(value > bundle.as_of_cutoff for value in effective_times):
            raise ValuationSnapshotError("capital_effective_time_after_cutoff")
        return FreshnessInput(
            capital=capital,
            policy_version=FRESHNESS_POLICY_VERSION,
        )


__all__ = [
    "FrozenEvidenceCapitalFreshnessPort",
    "FrozenEvidenceCapitalPort",
]
