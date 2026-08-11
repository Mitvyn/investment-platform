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
_SHARES = (
    r"(?P<value>[0-9][0-9,]*(?:\.[0-9]+)?)"
    r"(?:\s+(?P<scale>thousand|million|billion))?"
)
_AMOUNT = r"(?P<value>[0-9][0-9,]*(?:\.[0-9]+)?)"


@dataclass(frozen=True, slots=True)
class _MetricSpec:
    field_id: str
    metric_key: str
    unit: str
    pattern: re.Pattern[str]
    required: bool = True


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
        field_id="warrants",
        metric_key="warrant_shares_outstanding",
        unit="shares",
        pattern=re.compile(r"\bwarrants?\b", re.IGNORECASE),
        required=False,
    ),
    _MetricSpec(
        field_id="convertibles",
        metric_key="convertible_share_equivalents",
        unit="shares",
        pattern=re.compile(
            r"\bconvertible (?:notes?|debt|securities)\b",
            re.IGNORECASE,
        ),
        required=False,
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
        field_id="preferreds",
        metric_key="preferred_shares_outstanding",
        unit="shares",
        pattern=re.compile(
            r"\bpreferred (?:stock|shares?|securities)\b",
            re.IGNORECASE,
        ),
        required=False,
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
_WARRANT_OBSERVATION = re.compile(
    _DATE + r"\s+warrants? outstanding\s+" + _SHARES + r"\b",
    re.IGNORECASE,
)
_CONVERTIBLE_OBSERVATION = re.compile(
    (
        r"\bas of "
        + _DATE
        + r",?\s+convertible (?:notes?|debt|securities)\b"
        + r".*?\bconvertible into\s+"
        + _SHARES
        + r"\s+shares?\b"
    ),
    re.IGNORECASE,
)
_PREFERRED_ZERO_OBSERVATION = re.compile(
    r"\bno preferred shares? outstanding as of " + _DATE + r"\b",
    re.IGNORECASE,
)
_PREFERRED_OBSERVATION = re.compile(
    (
        r"\bpreferred (?:stock|shares?|securities)\b"
        r"\s+outstanding as of " + _DATE + r"\s+" + _SHARES + r"(?:\s+shares?)?\b"
    ),
    re.IGNORECASE,
)
_TABLE_SCALE_MARKER = re.compile(
    r"\(\s*in\s+(?P<scale_description>[^)]+)\)",
    re.IGNORECASE,
)
_POTENTIAL_SCALE_PREFIX = re.compile(
    r"^(?:hundreds?|thousands?|millions?|billions?)\b",
    re.IGNORECASE,
)
_TABLE_CONTEXT_BOUNDARY = re.compile(r"[.!?]\s+")
_TABLE_CONTEXT_HEADING = re.compile(
    (
        r"\b[A-Za-z][A-Za-z0-9/-]*"
        r"(?:\s+[A-Za-z][A-Za-z0-9/-]*){0,5}"
        r"\s+(?:table|schedule)\s*:"
    ),
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


def _table_scale(text: str, *, before: int) -> str | None:
    context_start = 0
    for boundary in _TABLE_CONTEXT_BOUNDARY.finditer(text[:before]):
        context_start = boundary.end()
    heading_context_start = context_start
    for heading in _TABLE_CONTEXT_HEADING.finditer(text[heading_context_start:before]):
        context_start = heading_context_start + heading.end()
    scale_names: list[str] = []
    for marker in _TABLE_SCALE_MARKER.finditer(text[context_start:before]):
        marker_end = context_start + marker.end()
        if any(character.isdigit() for character in text[marker_end:before]):
            continue
        description = " ".join(marker.group("scale_description").split()).casefold()
        if not _POTENTIAL_SCALE_PREFIX.match(description):
            continue
        if description.endswith("except share and per share amounts"):
            continue
        candidate = description.removesuffix("s")
        if candidate not in _SCALE:
            raise FilingFinancingMetricError(
                "filing financing table scale is unrecognized"
            )
        scale_names.append(candidate)
    if len(scale_names) > 1:
        raise FilingFinancingMetricError("filing financing table scale is ambiguous")
    return scale_names[0] if scale_names else None


def _observation(
    spec: _MetricSpec,
    passage: PrimaryEvidencePassage,
    text: str,
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
    if spec.unit == "shares":
        table_scale = _table_scale(text, before=match.start())
        if scale_name is not None and table_scale is not None:
            raise FilingFinancingMetricError(
                "filing financing table scale is ambiguous"
            )
        scale_name = scale_name or table_scale
    scale_key = scale_name.casefold().removesuffix("s") if scale_name else None
    scale = _SCALE[scale_key]
    value_text = match.groupdict().get("value")
    value = _decimal(value_text) if value_text is not None else Decimal(0)
    scaled_value = value * scale
    if spec.unit == "shares" and scaled_value != scaled_value.to_integral_value():
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


def _matches_for_spec(
    spec: _MetricSpec,
    text: str,
) -> tuple[re.Match[str], ...]:
    if not spec.pattern.search(text):
        return ()
    if spec.field_id == "warrants":
        patterns = (_WARRANT_OBSERVATION,)
    elif spec.field_id == "convertibles":
        patterns = (_CONVERTIBLE_OBSERVATION,)
    elif spec.field_id == "preferreds":
        patterns = (_PREFERRED_ZERO_OBSERVATION, _PREFERRED_OBSERVATION)
    elif spec.unit == "shares":
        patterns = (_SHARE_OBSERVATION,)
    else:
        patterns = (spec.pattern,)
    return tuple(
        match
        for observation_pattern in patterns
        for match in observation_pattern.finditer(text)
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
            by_field[spec.field_id].extend(
                _observation(spec, passage, text, match)
                for match in _matches_for_spec(spec, text)
            )

    metrics: list[NormalizedMetricFact] = []
    for spec in _SPECS:
        observations = by_field[spec.field_id]
        if not observations:
            if not spec.required:
                continue
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
