from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re
import unicodedata

from .pipeline import NormalizedMetricFact, PrimaryEvidencePassage


FINANCING_SEMANTIC_POLICY_VERSION = "biotech-financing-semantics-v1"
FINANCING_FIELD_IDS = (
    "basic_shares",
    "options",
    "warrants",
    "convertibles",
    "rsus",
    "preferreds",
    "atm_shelf_capacity",
    "share_growth",
)
FINANCING_FIELD_OUTCOMES = frozenset({"complete", "absent", "not_applicable"})
FINANCING_METRIC_KEYS_BY_FIELD = {
    "basic_shares": frozenset({"basic_shares_outstanding"}),
    "options": frozenset({"option_shares_outstanding"}),
    "warrants": frozenset({"warrant_shares_outstanding"}),
    "convertibles": frozenset({"convertible_share_equivalents"}),
    "rsus": frozenset({"rsu_shares_outstanding"}),
    "preferreds": frozenset({"preferred_shares_outstanding"}),
    "atm_shelf_capacity": frozenset({"atm_capacity", "shelf_capacity"}),
    "share_growth": frozenset({"basic_share_growth", "share_count_growth"}),
}
FINANCING_PASSAGE_ALIASES_BY_FIELD = {
    "basic_shares": (
        "basic shares",
        "common shares outstanding",
        "common stock outstanding",
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
    ),
    "options": (
        "stock options",
        "options outstanding",
        "option shares",
    ),
    "warrants": (
        "warrants",
        "warrant shares",
    ),
    "convertibles": (
        "convertible notes",
        "convertible debt",
        "convertible securities",
        "conversion shares",
    ),
    "rsus": (
        "restricted stock units",
        "restricted stock awards",
        "rsus",
    ),
    "preferreds": (
        "preferred stock",
        "preferred shares",
        "preferred securities",
    ),
    "atm_shelf_capacity": (
        "at the market program",
        "at the market offering",
        "atm program",
        "sales agreement prospectus supplement",
        "shelf registration",
        "shelf capacity",
    ),
    "share_growth": (
        "share count growth",
        "shares increased",
        "weighted average shares",
        "year over year shares",
        "share growth",
    ),
}
_ATM_CAPACITY_AMOUNT_PATTERN = re.compile(
    r"(?:\$\s*|usd\s+)(?P<amount>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?P<scale>thousand|million|billion))?",
    re.IGNORECASE,
)
_ATM_CAPACITY_CONTEXT_PATTERN = re.compile(
    r"\b(?:up to|maximum aggregate offering price|aggregate amount|"
    r"remained available|remaining capacity|shelf capacity|atm capacity|"
    r"at[-\s]+the[-\s]+market program capacity)\b",
    re.IGNORECASE,
)


class FinancingSemanticError(ValueError):
    """Raised when financing evidence cannot satisfy the semantic contract."""


@dataclass(frozen=True, slots=True)
class FinancingFieldEvidence:
    field_id: str
    outcome: str
    evidence_reference_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FinancingSemanticMatrix:
    policy_version: str
    coverage_state: str
    outcomes: tuple[FinancingFieldEvidence, ...]
    reason_codes: tuple[str, ...]
    metrics: tuple[NormalizedMetricFact, ...]


@dataclass(frozen=True, slots=True)
class NormalizedFinancingFact:
    policy_version: str
    reference_key: str
    source_class: str
    field_id: str
    outcome: str
    metric_reference_key: str | None
    metric_key: str | None
    value: str | None
    unit: str | None
    period_start: date | None
    period_end: date | None
    calculation_method: str | None
    formula: str | None
    evidence_reference_keys: tuple[str, ...]
    supporting_passage_keys: tuple[str, ...]


def _normalize_semantic_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("&", " and ")
    return " ".join(re.sub(r"[^\w]+", " ", normalized).split())


def _passage_supports_field(
    passage: PrimaryEvidencePassage,
    field_id: str,
) -> bool:
    normalized_text = _normalize_semantic_text(passage.passage_text)
    return any(
        _normalize_semantic_text(alias) in normalized_text
        for alias in FINANCING_PASSAGE_ALIASES_BY_FIELD[field_id]
    )


def _passage_supports_metric_field(
    passage: PrimaryEvidencePassage,
    metric: NormalizedMetricFact,
    field_id: str,
) -> bool:
    if _passage_supports_field(passage, field_id):
        return True
    return (
        field_id == "share_growth"
        and metric.metric_key == "basic_share_growth"
        and (
            passage.reference_key.startswith(
                "sec-companyfacts:basic_shares_outstanding:"
            )
            or passage.reference_key.startswith("corporate-action:")
        )
    )


def _passage_declares_absence(
    passage: PrimaryEvidencePassage,
    field_id: str,
) -> bool:
    normalized_text = _normalize_semantic_text(passage.passage_text)
    return any(
        any(
            phrase in normalized_text
            for phrase in (
                f"no {normalized_alias}",
                f"no shares of {normalized_alias}",
                f"no {normalized_alias} outstanding",
                f"without {normalized_alias}",
                f"zero {normalized_alias}",
                f"{normalized_alias} zero",
                f"{normalized_alias} none",
            )
        )
        for alias in FINANCING_PASSAGE_ALIASES_BY_FIELD[field_id]
        if (normalized_alias := _normalize_semantic_text(alias))
    )


def _passage_declares_not_applicable(
    passage: PrimaryEvidencePassage,
    field_id: str,
) -> bool:
    normalized_text = _normalize_semantic_text(passage.passage_text)
    return any(
        any(
            phrase in normalized_text
            for phrase in (
                f"{normalized_alias} not applicable",
                f"{normalized_alias} are not applicable",
                f"{normalized_alias} is not applicable",
                f"not applicable {normalized_alias}",
                f"{normalized_alias} does not apply",
            )
        )
        for alias in FINANCING_PASSAGE_ALIASES_BY_FIELD[field_id]
        if (normalized_alias := _normalize_semantic_text(alias))
    )


def _passage_is_hypothetical(
    passage: PrimaryEvidencePassage,
) -> bool:
    normalized_text = _normalize_semantic_text(passage.passage_text)
    return any(
        phrase in normalized_text
        for phrase in (
            "may offer",
            "may issue",
            "future offerings",
            "could result",
            "to the extent that",
        )
    )


def _passage_reports_numeric_atm_capacity(
    passage: PrimaryEvidencePassage,
) -> bool:
    text = unicodedata.normalize("NFKC", passage.passage_text)
    if _ATM_CAPACITY_CONTEXT_PATTERN.search(text) is None:
        return False
    for match in _ATM_CAPACITY_AMOUNT_PATTERN.finditer(text):
        try:
            if Decimal(match.group("amount").replace(",", "")) > 0:
                return True
        except InvalidOperation:
            continue
    return False


def _metric_decimal(metric: NormalizedMetricFact) -> Decimal:
    try:
        return Decimal(metric.value)
    except InvalidOperation as error:
        raise FinancingSemanticError(
            f"{metric.metric_key} value is not canonical numeric evidence"
        ) from error


def financing_missing_field_reason_codes(
    field_evidence: tuple[FinancingFieldEvidence, ...],
) -> tuple[str, ...]:
    present_fields = {
        outcome.field_id
        for outcome in field_evidence
        if outcome.field_id in FINANCING_FIELD_IDS
    }
    return tuple(
        f"financing_field_{field_id}_unresolved"
        for field_id in FINANCING_FIELD_IDS
        if field_id not in present_fields
    )


def derive_financing_field_evidence(
    *,
    passages: tuple[PrimaryEvidencePassage, ...],
    metrics: tuple[NormalizedMetricFact, ...],
) -> tuple[FinancingFieldEvidence, ...]:
    """Derive only field outcomes explicitly supported by normalized evidence."""

    passages_by_reference = {passage.reference_key: passage for passage in passages}
    if len(passages_by_reference) != len(passages):
        raise FinancingSemanticError("duplicate financing passage reference")
    metrics_by_reference = {metric.reference_key: metric for metric in metrics}
    if len(metrics_by_reference) != len(metrics):
        raise FinancingSemanticError("duplicate financing metric reference")
    outcomes: list[FinancingFieldEvidence] = []
    for field_id in FINANCING_FIELD_IDS:
        field_metrics = tuple(
            metric
            for metric in metrics
            if (
                metric.source_class == "financing"
                and metric.metric_key in FINANCING_METRIC_KEYS_BY_FIELD[field_id]
            )
        )
        supporting_keys = tuple(
            dict.fromkeys(
                support_key
                for metric in field_metrics
                for support_key in metric.supporting_passage_keys
            )
        )
        direct_passages = tuple(
            passage
            for passage in passages
            if (
                passage.source_class == "financing"
                and _passage_supports_field(passage, field_id)
            )
        )
        support_passages = tuple(
            passages_by_reference[key]
            for key in supporting_keys
            if key in passages_by_reference
        )
        field_passages = tuple(dict.fromkeys((*support_passages, *direct_passages)))
        if not field_passages:
            continue
        declares_absence = any(
            _passage_declares_absence(passage, field_id) for passage in field_passages
        )
        declares_not_applicable = any(
            _passage_declares_not_applicable(passage, field_id)
            for passage in field_passages
        )
        hypothetical = any(
            _passage_is_hypothetical(passage) for passage in field_passages
        )
        has_positive_passage = any(
            not _passage_declares_absence(passage, field_id)
            and not _passage_declares_not_applicable(passage, field_id)
            and not _passage_is_hypothetical(passage)
            and (
                field_id != "atm_shelf_capacity"
                or _passage_reports_numeric_atm_capacity(passage)
            )
            for passage in field_passages
        )
        metric_values = tuple(_metric_decimal(metric) for metric in field_metrics)
        has_positive_metric = any(value != 0 for value in metric_values)
        if declares_absence and (
            has_positive_metric or has_positive_passage or declares_not_applicable
        ):
            continue
        if declares_not_applicable and (
            field_metrics or has_positive_passage or hypothetical
        ):
            continue
        if (
            field_id == "atm_shelf_capacity"
            and not has_positive_metric
            and not has_positive_passage
            and not declares_absence
            and not declares_not_applicable
        ):
            continue
        if declares_absence:
            outcome = "absent"
        elif declares_not_applicable:
            outcome = "not_applicable"
        elif hypothetical:
            continue
        else:
            outcome = "complete"
        evidence_keys = (
            tuple(metric.reference_key for metric in field_metrics)
            if field_metrics
            else tuple(passage.reference_key for passage in field_passages)
        )
        outcomes.append(
            FinancingFieldEvidence(
                field_id=field_id,
                outcome=outcome,
                evidence_reference_keys=evidence_keys,
            )
        )
    return tuple(outcomes)


def build_financing_semantic_matrix(
    *,
    field_evidence: tuple[FinancingFieldEvidence, ...],
    passages: tuple[PrimaryEvidencePassage, ...],
    metrics: tuple[NormalizedMetricFact, ...],
) -> FinancingSemanticMatrix:
    field_ids = tuple(outcome.field_id for outcome in field_evidence)
    for field_id in field_ids:
        if field_ids.count(field_id) > 1:
            raise FinancingSemanticError(f"duplicate field outcome: {field_id}")
    outcomes_by_field = {outcome.field_id: outcome for outcome in field_evidence}
    unknown_fields = tuple(
        field_id
        for field_id in outcomes_by_field
        if field_id not in FINANCING_FIELD_IDS
    )
    if unknown_fields:
        raise FinancingSemanticError(
            f"unknown financing fields: {', '.join(sorted(unknown_fields))}"
        )
    missing_fields = tuple(
        field_id
        for field_id in FINANCING_FIELD_IDS
        if field_id not in outcomes_by_field
    )
    if missing_fields:
        raise FinancingSemanticError(
            f"missing required fields: {', '.join(missing_fields)}"
        )
    for field_id in FINANCING_FIELD_IDS:
        if outcomes_by_field[field_id].outcome not in FINANCING_FIELD_OUTCOMES:
            raise FinancingSemanticError(f"{field_id} outcome is invalid")
    passages_by_reference = {passage.reference_key: passage for passage in passages}
    metrics_by_reference = {metric.reference_key: metric for metric in metrics}
    evidence_reference_keys = passages_by_reference.keys() | metrics_by_reference.keys()
    for field_id in FINANCING_FIELD_IDS:
        outcome = outcomes_by_field[field_id]
        if not outcome.evidence_reference_keys or any(
            reference_key not in evidence_reference_keys
            for reference_key in outcome.evidence_reference_keys
        ):
            raise FinancingSemanticError(f"{field_id} evidence reference is unresolved")
        for reference_key in outcome.evidence_reference_keys:
            passage = passages_by_reference.get(reference_key)
            if passage is not None and passage.source_class != "financing":
                raise FinancingSemanticError(
                    f"{field_id} passage evidence is not financing evidence"
                )
            if passage is not None and not _passage_supports_field(
                passage,
                field_id,
            ):
                raise FinancingSemanticError(
                    f"{field_id} passage is not semantically field-specific"
                )
            metric = metrics_by_reference.get(reference_key)
            if metric is not None and metric.source_class != "financing":
                raise FinancingSemanticError(
                    f"{field_id} metric evidence is not financing evidence"
                )
            if (
                metric is not None
                and metric.metric_key not in FINANCING_METRIC_KEYS_BY_FIELD[field_id]
            ):
                raise FinancingSemanticError(
                    f"{field_id} metric key is not field-specific"
                )
            if metric is not None and (
                not metric.supporting_passage_keys
                or any(
                    support_key not in passages_by_reference
                    or passages_by_reference[support_key].source_class != "financing"
                    for support_key in metric.supporting_passage_keys
                )
            ):
                raise FinancingSemanticError(f"{field_id} metric support is unresolved")
            if metric is not None and any(
                not _passage_supports_metric_field(
                    passages_by_reference[support_key],
                    metric,
                    field_id,
                )
                for support_key in metric.supporting_passage_keys
            ):
                raise FinancingSemanticError(
                    f"{field_id} metric support is not semantically field-specific"
                )
        field_metrics = tuple(
            metrics_by_reference[reference_key]
            for reference_key in outcome.evidence_reference_keys
            if reference_key in metrics_by_reference
        )
        field_passages = tuple(
            dict.fromkeys(
                (
                    *(
                        reference_key
                        for reference_key in outcome.evidence_reference_keys
                        if reference_key in passages_by_reference
                    ),
                    *(
                        support_key
                        for metric in field_metrics
                        for support_key in metric.supporting_passage_keys
                    ),
                )
            )
        )
        if outcome.outcome == "absent":
            if any(_metric_decimal(metric) != 0 for metric in field_metrics) or not any(
                _passage_declares_absence(
                    passages_by_reference[reference_key],
                    field_id,
                )
                for reference_key in field_passages
            ):
                raise FinancingSemanticError(
                    f"{field_id} absent outcome conflicts with evidence"
                )
        elif outcome.outcome == "complete":
            if (
                any(
                    _passage_declares_absence(
                        passages_by_reference[reference_key], field_id
                    )
                    or _passage_declares_not_applicable(
                        passages_by_reference[reference_key], field_id
                    )
                    or _passage_is_hypothetical(passages_by_reference[reference_key])
                    for reference_key in field_passages
                )
                or (
                    field_id != "share_growth"
                    and field_metrics
                    and not any(
                        _metric_decimal(metric) != 0 for metric in field_metrics
                    )
                )
                or (
                    field_id == "atm_shelf_capacity"
                    and not any(
                        _metric_decimal(metric) != 0 for metric in field_metrics
                    )
                    and not any(
                        _passage_reports_numeric_atm_capacity(
                            passages_by_reference[reference_key]
                        )
                        for reference_key in field_passages
                    )
                )
            ):
                raise FinancingSemanticError(
                    f"{field_id} complete outcome conflicts with evidence"
                )
        elif field_metrics or not any(
            _passage_declares_not_applicable(
                passages_by_reference[reference_key],
                field_id,
            )
            for reference_key in field_passages
        ):
            raise FinancingSemanticError(
                f"{field_id} not_applicable outcome conflicts with evidence"
            )
    referenced_metric_keys = {
        reference_key
        for outcome in field_evidence
        for reference_key in outcome.evidence_reference_keys
        if reference_key in metrics_by_reference
    }
    return FinancingSemanticMatrix(
        policy_version=FINANCING_SEMANTIC_POLICY_VERSION,
        coverage_state="complete",
        outcomes=tuple(outcomes_by_field[field_id] for field_id in FINANCING_FIELD_IDS),
        reason_codes=(),
        metrics=tuple(
            sorted(
                (
                    metrics_by_reference[reference_key]
                    for reference_key in referenced_metric_keys
                ),
                key=lambda metric: metric.reference_key,
            )
        ),
    )


def financing_matrix_to_normalized_facts(
    matrix: FinancingSemanticMatrix,
) -> tuple[NormalizedFinancingFact, ...]:
    if (
        matrix.policy_version != FINANCING_SEMANTIC_POLICY_VERSION
        or matrix.coverage_state != "complete"
        or matrix.reason_codes
        or tuple(outcome.field_id for outcome in matrix.outcomes) != FINANCING_FIELD_IDS
    ):
        raise FinancingSemanticError("financing semantic matrix is not complete")
    metrics_by_reference = {metric.reference_key: metric for metric in matrix.metrics}
    if len(metrics_by_reference) != len(matrix.metrics):
        raise FinancingSemanticError("financing semantic matrix has duplicate metrics")
    facts: list[NormalizedFinancingFact] = []
    for outcome in matrix.outcomes:
        if outcome.outcome not in FINANCING_FIELD_OUTCOMES:
            raise FinancingSemanticError("financing semantic matrix is not complete")
        field_metrics = tuple(
            sorted(
                (
                    metrics_by_reference[reference_key]
                    for reference_key in outcome.evidence_reference_keys
                    if reference_key in metrics_by_reference
                ),
                key=lambda metric: metric.reference_key,
            )
        )
        for metric in field_metrics:
            if (
                metric.source_class != "financing"
                or metric.metric_key
                not in FINANCING_METRIC_KEYS_BY_FIELD[outcome.field_id]
            ):
                raise FinancingSemanticError(
                    f"{outcome.field_id} normalized metric is invalid"
                )
            facts.append(
                NormalizedFinancingFact(
                    policy_version=matrix.policy_version,
                    reference_key=metric.reference_key,
                    source_class="financing",
                    field_id=outcome.field_id,
                    outcome=outcome.outcome,
                    metric_reference_key=metric.reference_key,
                    metric_key=metric.metric_key,
                    value=metric.value,
                    unit=metric.unit,
                    period_start=metric.period_start,
                    period_end=metric.period_end,
                    calculation_method=metric.calculation_method,
                    formula=metric.formula,
                    evidence_reference_keys=outcome.evidence_reference_keys,
                    supporting_passage_keys=(metric.supporting_passage_keys),
                )
            )
        if not field_metrics:
            facts.append(
                NormalizedFinancingFact(
                    policy_version=matrix.policy_version,
                    reference_key=(f"financing-semantic:{outcome.field_id}"),
                    source_class="financing",
                    field_id=outcome.field_id,
                    outcome=outcome.outcome,
                    metric_reference_key=None,
                    metric_key=None,
                    value=None,
                    unit=None,
                    period_start=None,
                    period_end=None,
                    calculation_method=None,
                    formula=None,
                    evidence_reference_keys=outcome.evidence_reference_keys,
                    supporting_passage_keys=(),
                )
            )
    return tuple(facts)


__all__ = [
    "FINANCING_FIELD_IDS",
    "FINANCING_FIELD_OUTCOMES",
    "FINANCING_METRIC_KEYS_BY_FIELD",
    "FINANCING_PASSAGE_ALIASES_BY_FIELD",
    "FINANCING_SEMANTIC_POLICY_VERSION",
    "FinancingFieldEvidence",
    "FinancingSemanticError",
    "FinancingSemanticMatrix",
    "NormalizedFinancingFact",
    "build_financing_semantic_matrix",
    "derive_financing_field_evidence",
    "financing_missing_field_reason_codes",
    "financing_matrix_to_normalized_facts",
]
