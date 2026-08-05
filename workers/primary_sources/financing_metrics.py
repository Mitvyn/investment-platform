from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re

from .pipeline import NormalizedMetricFact, PrimaryEvidencePassage


class FilingFinancingMetricError(ValueError):
    """Raised when filing passages cannot support exact financing metrics."""


_DATE = (
    r"(?P<date>"
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December) [0-9]{1,2}, [0-9]{4})"
)
_SHARES = r"(?P<value>[0-9][0-9,]*)"
_AMOUNT = r"(?P<value>[0-9][0-9,]*(?:\.[0-9]+)?)"


@dataclass(frozen=True, slots=True)
class _MetricSpec:
    field_id: str
    metric_key: str
    unit: str
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class _Observation:
    spec: _MetricSpec
    passage: PrimaryEvidencePassage
    period_end: date
    value: Decimal
    scale: Decimal


_SPECS = (
    _MetricSpec(
        field_id="options",
        metric_key="option_shares_outstanding",
        unit="shares",
        pattern=re.compile(
            (
                r"\b(?:stock options?|options?)\b"
                r".*?\bweighted[- ]average exercise price\b"
            ),
            re.IGNORECASE,
        ),
    ),
    _MetricSpec(
        field_id="rsus",
        metric_key="rsu_shares_outstanding",
        unit="shares",
        pattern=re.compile(
            (
                r"\b(?:restricted stock units?|rsus?)\b"
                r".*?\bstock units\b"
                r".*?\bweighted[- ]average grant date fair value\b"
            ),
            re.IGNORECASE,
        ),
    ),
    _MetricSpec(
        field_id="atm_shelf_capacity",
        metric_key="atm_capacity",
        unit="USD",
        pattern=re.compile(
            (
                r"\b(?:at[- ]the[- ]market|atm)\b"
                r".*?\bas of "
                + _DATE
                + r",?\s+(?:an amount of\s+)?\$\s*"
                + _AMOUNT
                + r"\s*(?P<scale>thousand|million|billion)?"
                r"\s+remained available for future sales\b"
            ),
            re.IGNORECASE,
        ),
    ),
)
_SHARE_OBSERVATION = re.compile(
    r"\boutstanding as of " + _DATE + r"\s+" + _SHARES + r"\b",
    re.IGNORECASE,
)
_SCALE = {
    None: Decimal(1),
    "thousand": Decimal(1_000),
    "million": Decimal(1_000_000),
    "billion": Decimal(1_000_000_000),
}


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _period_end(value: str) -> date:
    try:
        return datetime.strptime(value, "%B %d, %Y").date()
    except ValueError as error:
        raise FilingFinancingMetricError(
            "filing financing metric date is invalid"
        ) from error


def _decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value.replace(",", ""))
    except InvalidOperation as error:
        raise FilingFinancingMetricError(
            "filing financing metric value is invalid"
        ) from error
    if not parsed.is_finite() or parsed < 0:
        raise FilingFinancingMetricError("filing financing metric value is invalid")
    return parsed


def _canonical_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _observation(
    spec: _MetricSpec,
    passage: PrimaryEvidencePassage,
    match: re.Match[str],
) -> _Observation:
    if (
        passage.source_class != "financing"
        or passage.origin_policy_version != "sec-origin-v1"
        or passage.coverage_keys
        or not passage.reference_key.strip()
    ):
        raise FilingFinancingMetricError(
            "filing financing metric provenance is invalid"
        )
    scale_name = match.groupdict().get("scale")
    scale = _SCALE[scale_name.casefold() if isinstance(scale_name, str) else None]
    value = _decimal(match.group("value"))
    if spec.unit == "shares" and value != value.to_integral_value():
        raise FilingFinancingMetricError(
            "filing financing share value must be integral"
        )
    return _Observation(
        spec=spec,
        passage=passage,
        period_end=_period_end(match.group("date")),
        value=value,
        scale=scale,
    )


def normalize_filing_financing_metrics(
    passages: tuple[PrimaryEvidencePassage, ...],
) -> tuple[NormalizedMetricFact, ...]:
    reference_keys = tuple(passage.reference_key for passage in passages)
    if not passages or len(reference_keys) != len(set(reference_keys)):
        raise FilingFinancingMetricError("filing financing passage identity is invalid")
    by_field: dict[str, list[_Observation]] = {spec.field_id: [] for spec in _SPECS}
    for passage in passages:
        text = _normalized_text(passage.passage_text)
        for spec in _SPECS:
            matches = (
                _SHARE_OBSERVATION.finditer(text)
                if spec.unit == "shares" and spec.pattern.search(text)
                else spec.pattern.finditer(text)
            )
            by_field[spec.field_id].extend(
                _observation(spec, passage, match) for match in matches
            )

    metrics: list[NormalizedMetricFact] = []
    for spec in _SPECS:
        observations = by_field[spec.field_id]
        if not observations:
            raise FilingFinancingMetricError(
                f"{spec.field_id} filing financing passage is missing"
            )
        latest_period = max(observation.period_end for observation in observations)
        observations = [
            observation
            for observation in observations
            if observation.period_end == latest_period
        ]
        identities = {
            (
                observation.period_end,
                observation.value * observation.scale,
            )
            for observation in observations
        }
        if len(identities) > 1:
            raise FilingFinancingMetricError(
                f"{spec.field_id} filing financing passages conflict"
            )
        if len(observations) > 1:
            raise FilingFinancingMetricError(
                f"{spec.field_id} filing financing passage is ambiguous"
            )
        observation = observations[0]
        normalized_value = observation.value * observation.scale
        derived = observation.scale != 1
        metrics.append(
            NormalizedMetricFact(
                reference_key=f"financing-metric:{spec.field_id}",
                source_class="financing",
                metric_key=spec.metric_key,
                value=_canonical_decimal(normalized_value),
                unit=spec.unit,
                period_start=None,
                period_end=observation.period_end,
                calculation_method="derived" if derived else "reported",
                formula=(
                    f"reported_amount*{_canonical_decimal(observation.scale)}"
                    if derived
                    else None
                ),
                supporting_passage_keys=(observation.passage.reference_key,),
            )
        )
    return tuple(metrics)


__all__ = [
    "FilingFinancingMetricError",
    "normalize_filing_financing_metrics",
]
