from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from itertools import groupby
import re


BASIC_SHARE_GROWTH_POLICY_VERSION = "financing-basic-share-growth-v1"
_FORMULA = (
    "(current_basic_shares-adjusted_prior_basic_shares)*100/adjusted_prior_basic_shares"
)
_PERCENT_SCALE = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class BasicShareObservation:
    security_id: str
    cik: str
    period_end: date
    accession_number: str
    accepted_at: datetime
    reference_key: str
    value: str
    unit: str
    concept: str
    measurement_basis: str
    economic_basis: str
    is_amendment: bool = False


@dataclass(frozen=True, slots=True)
class CorporateActionReconciliation:
    security_id: str
    cik: str
    from_period_end: date
    to_period_end: date
    state: str
    prior_to_current_factor: str
    evidence_reference_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BasicShareGrowthResult:
    policy_version: str
    state: str
    security_id: str | None
    cik: str | None
    current_accession_number: str | None
    prior_accession_number: str | None
    current_reference_key: str | None
    prior_reference_key: str | None
    current_shares: str | None
    prior_shares: str | None
    adjusted_prior_shares: str | None
    delta_shares: str | None
    growth_percent: str | None
    unit: str
    period_start: date | None
    period_end: date | None
    formula: str
    evidence_reference_keys: tuple[str, ...]
    reason_codes: tuple[str, ...]


def _gap(
    state: str,
    reason_code: str,
) -> BasicShareGrowthResult:
    return BasicShareGrowthResult(
        policy_version=BASIC_SHARE_GROWTH_POLICY_VERSION,
        state=state,
        security_id=None,
        cik=None,
        current_accession_number=None,
        prior_accession_number=None,
        current_reference_key=None,
        prior_reference_key=None,
        current_shares=None,
        prior_shares=None,
        adjusted_prior_shares=None,
        delta_shares=None,
        growth_percent=None,
        unit="percent",
        period_start=None,
        period_end=None,
        formula=_FORMULA,
        evidence_reference_keys=(),
        reason_codes=(reason_code,),
    )


def _fact_signature(
    observation: BasicShareObservation,
) -> tuple[str, str, str, str, str]:
    return (
        observation.value,
        observation.unit,
        observation.concept,
        observation.measurement_basis,
        observation.economic_basis,
    )


def _resolve_period(
    period_observations: tuple[BasicShareObservation, ...],
) -> BasicShareObservation | None:
    amendments = tuple(
        observation for observation in period_observations if observation.is_amendment
    )
    candidates = amendments or period_observations
    if amendments:
        latest_accepted_at = max(observation.accepted_at for observation in amendments)
        candidates = tuple(
            observation
            for observation in amendments
            if observation.accepted_at == latest_accepted_at
        )
    if len({_fact_signature(item) for item in candidates}) != 1:
        return None
    return max(
        candidates,
        key=lambda item: (
            item.accepted_at,
            item.accession_number,
            item.reference_key,
        ),
    )


def _parse_share_value(value: str) -> Decimal | None:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite() or parsed < 0 or parsed != parsed.to_integral_value():
        return None
    return parsed


def _parse_positive_decimal(value: str) -> Decimal | None:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite() or parsed <= 0:
        return None
    return parsed


def _format_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _has_timezone(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _has_valid_reference(
    observation: BasicShareObservation,
) -> bool:
    return bool(
        observation.reference_key.strip()
        and re.fullmatch(
            r"\d{10}-\d{2}-\d{6}",
            observation.accession_number,
        )
    )


def calculate_basic_share_growth(
    *,
    observations: tuple[BasicShareObservation, ...],
    as_of_cutoff: datetime,
    corporate_action_reconciliation: (CorporateActionReconciliation | None) = None,
) -> BasicShareGrowthResult:
    if not _has_timezone(as_of_cutoff) or any(
        not _has_timezone(observation.accepted_at) for observation in observations
    ):
        return _gap(
            "indeterminate",
            "basic_share_growth_publication_time_indeterminate",
        )
    eligible = tuple(
        observation
        for observation in observations
        if observation.accepted_at <= as_of_cutoff
    )
    ordered = sorted(eligible, key=lambda item: item.period_end)
    if not ordered:
        return _gap(
            "incomplete",
            "basic_share_growth_current_fact_missing",
        )
    identities = {(observation.security_id, observation.cik) for observation in ordered}
    if len(identities) != 1:
        return _gap(
            "indeterminate",
            "basic_share_growth_identity_mismatch",
        )
    if len({observation.period_end for observation in ordered}) < 2:
        return _gap(
            "incomplete",
            "basic_share_growth_prior_fact_missing",
        )
    resolved: list[BasicShareObservation] = []
    for _, period_items in groupby(
        ordered,
        key=lambda item: item.period_end,
    ):
        resolved_observation = _resolve_period(tuple(period_items))
        if resolved_observation is None:
            return _gap(
                "indeterminate",
                "basic_share_growth_conflicting_fact",
            )
        resolved.append(resolved_observation)
    prior, current = resolved[-2:]
    if (
        not _has_valid_reference(prior)
        or not _has_valid_reference(current)
        or prior.reference_key == current.reference_key
    ):
        return _gap(
            "indeterminate",
            "basic_share_growth_reference_invalid",
        )
    if (
        prior.measurement_basis == "weighted_average"
        or current.measurement_basis == "weighted_average"
    ):
        return _gap(
            "indeterminate",
            "basic_share_growth_weighted_average_input_rejected",
        )
    if prior.measurement_basis != current.measurement_basis:
        return _gap(
            "indeterminate",
            "basic_share_growth_measurement_basis_mismatch",
        )
    if prior.measurement_basis != "point_in_time":
        return _gap(
            "indeterminate",
            "basic_share_growth_measurement_basis_invalid",
        )
    if prior.unit != current.unit:
        return _gap(
            "indeterminate",
            "basic_share_growth_unit_mismatch",
        )
    if prior.concept != current.concept:
        return _gap(
            "indeterminate",
            "basic_share_growth_concept_mismatch",
        )
    if prior.economic_basis != current.economic_basis:
        return _gap(
            "indeterminate",
            "basic_share_growth_basis_mismatch",
        )
    current_value = _parse_share_value(current.value)
    prior_value = _parse_share_value(prior.value)
    if current_value is None or prior_value is None:
        return _gap(
            "indeterminate",
            "basic_share_growth_value_invalid",
        )
    if corporate_action_reconciliation is None:
        return _gap(
            "indeterminate",
            ("basic_share_growth_corporate_action_reconciliation_missing"),
        )
    reconciliation = corporate_action_reconciliation
    if (
        reconciliation.security_id != prior.security_id
        or reconciliation.cik != prior.cik
        or reconciliation.from_period_end != prior.period_end
        or reconciliation.to_period_end != current.period_end
    ):
        return _gap(
            "indeterminate",
            "basic_share_growth_corporate_action_mismatch",
        )
    if reconciliation.state == "unresolved":
        return _gap(
            "indeterminate",
            "basic_share_growth_corporate_action_unresolved",
        )
    if reconciliation.state != "verified":
        return _gap(
            "indeterminate",
            "basic_share_growth_corporate_action_invalid",
        )
    parsed_factor = _parse_positive_decimal(reconciliation.prior_to_current_factor)
    if (
        parsed_factor is None
        or not reconciliation.evidence_reference_keys
        or any(
            not reference_key.strip()
            for reference_key in reconciliation.evidence_reference_keys
        )
    ):
        return _gap(
            "indeterminate",
            "basic_share_growth_corporate_action_invalid",
        )
    adjusted_prior_value = prior_value * parsed_factor
    if adjusted_prior_value == 0:
        return _gap(
            "indeterminate",
            "basic_share_growth_prior_denominator_zero",
        )
    delta = current_value - adjusted_prior_value
    percent = ((delta * Decimal(100)) / adjusted_prior_value).quantize(
        _PERCENT_SCALE, rounding=ROUND_HALF_EVEN
    )
    return BasicShareGrowthResult(
        policy_version=BASIC_SHARE_GROWTH_POLICY_VERSION,
        state="complete",
        security_id=current.security_id,
        cik=current.cik,
        current_accession_number=current.accession_number,
        prior_accession_number=prior.accession_number,
        current_reference_key=current.reference_key,
        prior_reference_key=prior.reference_key,
        current_shares=_format_decimal(current_value),
        prior_shares=_format_decimal(prior_value),
        adjusted_prior_shares=_format_decimal(adjusted_prior_value),
        delta_shares=_format_decimal(delta),
        growth_percent=format(percent, "f"),
        unit="percent",
        period_start=prior.period_end,
        period_end=current.period_end,
        formula=_FORMULA,
        evidence_reference_keys=(
            prior.reference_key,
            current.reference_key,
            *reconciliation.evidence_reference_keys,
        ),
        reason_codes=("basic_share_growth_complete",),
    )


__all__ = [
    "BASIC_SHARE_GROWTH_POLICY_VERSION",
    "BasicShareGrowthResult",
    "BasicShareObservation",
    "CorporateActionReconciliation",
    "calculate_basic_share_growth",
]
