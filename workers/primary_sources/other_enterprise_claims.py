from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import re
from typing import Protocol


POLICY_VERSION = "biotech-other-enterprise-claims-v1"
COMPONENT_IDS = (
    "redeemable_preferred_claim",
    "noncontrolling_interest_claim",
    "royalty_monetization_liability",
    "contingent_consideration_claim",
    "pension_underfunded_claim",
    "finance_lease_claim",
)
_COMPONENT_LINE_ITEM_PATTERNS = {
    "redeemable_preferred_claim": (
        r"(?:redeemable\s+preferred|preferred\s+(?:stock|shares)\s+subject\s+to\s+redemption)"
        r"(?:\s+(?:stock|shares|equity))?"
    ),
    "noncontrolling_interest_claim": r"noncontrolling\s+interests?",
    "royalty_monetization_liability": (
        r"(?:royalty\s+monetization\s+liabilit(?:y|ies)|"
        r"liabilit(?:y|ies)\s+for\s+(?:the\s+)?sale\s+of\s+future\s+revenue)"
    ),
    "contingent_consideration_claim": r"contingent\s+consideration",
    "pension_underfunded_claim": (
        r"(?:underfunded\s+pension|pension(?:\s+and\s+postretirement)?\s+"
        r"(?:liabilit(?:y|ies)|obligations?))"
    ),
    "finance_lease_claim": r"finance\s+lease\s+(?:liabilit(?:y|ies)|obligations?)",
}


class OtherEnterpriseClaimsError(RuntimeError):
    """Raised when other enterprise claims cannot be resolved safely."""


class FilingDocument(Protocol):
    report_date: date | None
    source_url: str
    accession_number: str
    primary_document: str
    published_at: datetime | None
    retrieved_at: datetime
    content_sha256: str
    content_text: str


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


@dataclass(frozen=True, slots=True)
class ClaimObservation:
    component_id: str
    value: str
    unit: str
    period_end: date
    source_concept: str
    supporting_evidence_ids: tuple[str, ...]
    disjointness_evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ClaimDisclosure:
    component_id: str
    period_end: date
    state: str
    supporting_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExplicitClaimNegation:
    component_id: str
    period_end: date
    supporting_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OtherEnterpriseClaimsContext:
    as_of_cutoff: datetime
    balance_sheet_period_end: date
    debt_concept: str
    debt_includes_finance_leases: bool
    debt_includes_convertible_principal: bool
    convertible_share_equivalents: str
    preferred_share_equivalents: str


@dataclass(frozen=True, slots=True)
class ReconciledBalanceSheet:
    period_end: date
    unit: str
    total_assets: str
    total_liabilities_and_equity: str
    covered_component_ids: tuple[str, ...]
    present_component_ids: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class BalanceSheetProof:
    balance_sheet: ReconciledBalanceSheet
    reference_key: str
    source_locator: str
    canonical_url: str
    publication_at: datetime | None
    retrieved_at: datetime
    content_hash: str
    passage_text: str


@dataclass(frozen=True, slots=True)
class ResolvedClaimComponent:
    component_id: str
    value: str
    unit: str
    period_end: date
    resolution: str
    reason_code: str
    source_concept: str | None
    supporting_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OtherEnterpriseClaimsResult:
    policy_version: str
    value: str
    unit: str
    period_end: date
    calculation_method: str
    formula: str
    supporting_evidence_ids: tuple[str, ...]
    components: tuple[ResolvedClaimComponent, ...]


def _number(value: str, reason_code: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise OtherEnterpriseClaimsError(reason_code) from error
    if not parsed.is_finite() or parsed < 0:
        raise OtherEnterpriseClaimsError(reason_code)
    return parsed


def _canonical(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def extract_reconciled_balance_sheet(
    documents: tuple[FilingDocument, ...],
    *,
    period_end: date,
    present_component_ids: tuple[str, ...],
) -> BalanceSheetProof:
    heading = re.compile(r"(?:Condensed\s+)?Consolidated Balance Sheets?", re.I)
    end_marker = "See the accompanying notes"
    amount = r"\$?\s*\(?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*\)?"
    for document in documents:
        if document.report_date != period_end:
            continue
        parser = _VisibleTextParser()
        parser.feed(document.content_text)
        visible = " ".join(" ".join(parser.parts).split())
        heading_match = heading.search(visible)
        if heading_match is None:
            continue
        start = heading_match.start()
        end = visible.casefold().find(end_marker.casefold(), start)
        if end < 0:
            continue
        passage = visible[start:end].strip()
        scale_match = re.search(r"\(in (thousands|millions|billions)", passage, re.I)
        assets_match = re.search(rf"Total assets\s+{amount}", passage, re.I)
        liabilities_match = re.search(
            rf"Total liabilities and stockholders[’'] equity\s+{amount}",
            passage,
            re.I,
        )
        if scale_match is None or assets_match is None or liabilities_match is None:
            continue
        multiplier = {
            "thousands": Decimal(1_000),
            "millions": Decimal(1_000_000),
            "billions": Decimal(1_000_000_000),
        }[scale_match.group(1).casefold()]
        assets = Decimal(assets_match.group(1).replace(",", "")) * multiplier
        liabilities = Decimal(liabilities_match.group(1).replace(",", "")) * multiplier
        if assets != liabilities:
            continue
        component_line_items = {
            component_id: line_item_match
            for component_id in COMPONENT_IDS
            if (
                line_item_match := re.search(
                    rf"{_COMPONENT_LINE_ITEM_PATTERNS[component_id]}\s+{amount}",
                    passage,
                    re.I,
                )
            )
        }
        covered_component_ids = tuple(component_line_items)
        positive_face_component_ids = tuple(
            component_id
            for component_id, line_item_match in component_line_items.items()
            if Decimal(line_item_match.group(1).replace(",", "")) > 0
        )
        reference_key = f"sec-balance-sheet:{document.accession_number}"
        return BalanceSheetProof(
            balance_sheet=ReconciledBalanceSheet(
                period_end=period_end,
                unit="USD",
                total_assets=_canonical(assets),
                total_liabilities_and_equity=_canonical(liabilities),
                covered_component_ids=covered_component_ids,
                present_component_ids=tuple(
                    dict.fromkeys(
                        (*present_component_ids, *positive_face_component_ids)
                    )
                ),
                supporting_evidence_ids=(reference_key,),
                complete=covered_component_ids == COMPONENT_IDS,
            ),
            reference_key=reference_key,
            source_locator=(
                f"{document.accession_number}/{document.primary_document}#balance-sheet"
            ),
            canonical_url=document.source_url,
            publication_at=document.published_at,
            retrieved_at=document.retrieved_at,
            content_hash=document.content_sha256,
            passage_text=passage,
        )
    raise OtherEnterpriseClaimsError("other_claims_balance_sheet_proof_unavailable")


def resolve_other_enterprise_claims(
    context: OtherEnterpriseClaimsContext,
    *,
    observations: tuple[ClaimObservation, ...] = (),
    disclosures: tuple[ClaimDisclosure, ...] = (),
    explicit_negations: tuple[ExplicitClaimNegation, ...] = (),
    balance_sheet: ReconciledBalanceSheet | None = None,
) -> OtherEnterpriseClaimsResult:
    if context.balance_sheet_period_end > context.as_of_cutoff.date():
        raise OtherEnterpriseClaimsError(
            "other_claims_balance_sheet_period_after_cutoff"
        )

    grouped: dict[str, list[ClaimObservation]] = {}
    for observation in observations:
        if observation.component_id not in COMPONENT_IDS:
            raise OtherEnterpriseClaimsError(
                f"other_claims_component_unknown:{observation.component_id}"
            )
        grouped.setdefault(observation.component_id, []).append(observation)
    negations: dict[str, list[ExplicitClaimNegation]] = {}
    for negation in explicit_negations:
        if negation.component_id not in COMPONENT_IDS:
            raise OtherEnterpriseClaimsError(
                f"other_claims_component_unknown:{negation.component_id}"
            )
        negations.setdefault(negation.component_id, []).append(negation)
    disclosures_by_component: dict[str, list[ClaimDisclosure]] = {}
    for disclosure in disclosures:
        if disclosure.component_id not in COMPONENT_IDS:
            raise OtherEnterpriseClaimsError(
                f"other_claims_component_unknown:{disclosure.component_id}"
            )
        if disclosure.state not in {"contingent", "non_quantifiable"}:
            raise OtherEnterpriseClaimsError(
                f"other_claims_component_disclosure_invalid:{disclosure.component_id}"
            )
        disclosures_by_component.setdefault(disclosure.component_id, []).append(
            disclosure
        )

    resolved: list[ResolvedClaimComponent] = []
    for component_id in COMPONENT_IDS:
        candidates = grouped.get(component_id, [])
        current = [
            candidate
            for candidate in candidates
            if candidate.period_end == context.balance_sheet_period_end
        ]
        current_negations = [
            negation
            for negation in negations.get(component_id, [])
            if negation.period_end == context.balance_sheet_period_end
            and negation.supporting_evidence_ids
        ]
        if not current:
            current_disclosures = [
                disclosure
                for disclosure in disclosures_by_component.get(component_id, ())
                if disclosure.period_end == context.balance_sheet_period_end
                and disclosure.supporting_evidence_ids
            ]
            if current_disclosures:
                state = current_disclosures[0].state
                raise OtherEnterpriseClaimsError(
                    f"other_claims_component_{state}:{component_id}"
                )
            if current_negations:
                evidence_ids = tuple(
                    dict.fromkeys(
                        evidence_id
                        for negation in current_negations
                        for evidence_id in negation.supporting_evidence_ids
                    )
                )
                resolved.append(
                    ResolvedClaimComponent(
                        component_id=component_id,
                        value="0",
                        unit="USD",
                        period_end=context.balance_sheet_period_end,
                        resolution="explicit_negation",
                        reason_code="other_claims_zero_negated",
                        source_concept=None,
                        supporting_evidence_ids=evidence_ids,
                    )
                )
                continue
            if _supports_structural_absence(
                balance_sheet,
                context=context,
                component_id=component_id,
            ):
                assert balance_sheet is not None
                resolved.append(
                    ResolvedClaimComponent(
                        component_id=component_id,
                        value="0",
                        unit="USD",
                        period_end=context.balance_sheet_period_end,
                        resolution="structural_absence",
                        reason_code="other_claims_zero_structural",
                        source_concept=None,
                        supporting_evidence_ids=tuple(
                            dict.fromkeys(balance_sheet.supporting_evidence_ids)
                        ),
                    )
                )
                continue
            if any(
                candidate.period_end > context.as_of_cutoff.date()
                for candidate in candidates
            ):
                raise OtherEnterpriseClaimsError(
                    f"other_claims_component_after_cutoff:{component_id}"
                )
            if candidates or negations.get(component_id):
                raise OtherEnterpriseClaimsError(
                    f"other_claims_component_stale:{component_id}"
                )
            raise OtherEnterpriseClaimsError(
                f"other_claims_component_unevidenced:{component_id}"
            )
        if any(candidate.unit != "USD" for candidate in current):
            raise OtherEnterpriseClaimsError(
                f"other_claims_component_unit_invalid:{component_id}"
            )
        values = {
            _number(
                candidate.value,
                f"other_claims_component_negative:{component_id}",
            )
            for candidate in current
        }
        if len(values) != 1:
            raise OtherEnterpriseClaimsError(
                f"other_claims_component_ambiguous:{component_id}"
            )
        source_concepts = {candidate.source_concept for candidate in current}
        if len(source_concepts) != 1:
            raise OtherEnterpriseClaimsError(
                f"other_claims_component_source_concept_conflict:{component_id}"
            )
        candidate = current[0]
        if not candidate.supporting_evidence_ids:
            raise OtherEnterpriseClaimsError(
                f"other_claims_component_unevidenced:{component_id}"
            )
        evidence_ids = tuple(
            dict.fromkeys(
                evidence_id
                for corroborating_candidate in current
                for evidence_id in corroborating_candidate.supporting_evidence_ids
            )
        )
        value = next(iter(values))
        resolution = "tagged_zero" if value == 0 else "reported"
        resolved.append(
            ResolvedClaimComponent(
                component_id=component_id,
                value=_canonical(value),
                unit="USD",
                period_end=candidate.period_end,
                resolution=resolution,
                reason_code=(
                    "other_claims_zero_tagged"
                    if resolution == "tagged_zero"
                    else "other_claims_value_reported"
                ),
                source_concept=candidate.source_concept,
                supporting_evidence_ids=evidence_ids,
            )
        )

    resolved_by_id = {component.component_id: component for component in resolved}
    if (
        Decimal(resolved_by_id["finance_lease_claim"].value) > 0
        and context.debt_includes_finance_leases
    ):
        raise OtherEnterpriseClaimsError("other_claims_double_count_finance_lease")
    convertible_equivalents = _number(
        context.convertible_share_equivalents,
        "other_claims_convertible_share_equivalents_invalid",
    )
    if convertible_equivalents > 0 and context.debt_includes_convertible_principal:
        raise OtherEnterpriseClaimsError("other_claims_double_count_convertible")
    preferred_equivalents = _number(
        context.preferred_share_equivalents,
        "other_claims_preferred_share_equivalents_invalid",
    )
    redeemable_preferred = Decimal(resolved_by_id["redeemable_preferred_claim"].value)
    preferred_disjointness_ids = tuple(
        evidence_id
        for observation in grouped.get("redeemable_preferred_claim", ())
        if observation.period_end == context.balance_sheet_period_end
        for evidence_id in observation.disjointness_evidence_ids
    )
    if (
        preferred_equivalents > 0
        and redeemable_preferred > 0
        and not preferred_disjointness_ids
    ):
        raise OtherEnterpriseClaimsError("other_claims_double_count_preferred")

    total = sum((Decimal(component.value) for component in resolved), Decimal(0))
    return OtherEnterpriseClaimsResult(
        policy_version=POLICY_VERSION,
        value=_canonical(total),
        unit="USD",
        period_end=context.balance_sheet_period_end,
        calculation_method="derived",
        formula="sum(component_values)",
        supporting_evidence_ids=tuple(
            dict.fromkeys(
                evidence_id
                for component in resolved
                for evidence_id in component.supporting_evidence_ids
            )
        ),
        components=tuple(resolved),
    )


def _supports_structural_absence(
    balance_sheet: ReconciledBalanceSheet | None,
    *,
    context: OtherEnterpriseClaimsContext,
    component_id: str,
) -> bool:
    if balance_sheet is None or not balance_sheet.complete:
        return False
    if (
        balance_sheet.period_end != context.balance_sheet_period_end
        or balance_sheet.period_end > context.as_of_cutoff.date()
        or balance_sheet.unit != "USD"
        or not balance_sheet.supporting_evidence_ids
    ):
        return False
    assets = _number(
        balance_sheet.total_assets,
        "other_claims_structural_proof_invalid",
    )
    liabilities_and_equity = _number(
        balance_sheet.total_liabilities_and_equity,
        "other_claims_structural_proof_invalid",
    )
    if assets != liabilities_and_equity:
        return False
    if not set(balance_sheet.covered_component_ids) <= set(COMPONENT_IDS):
        return False
    if not set(balance_sheet.present_component_ids) <= set(
        balance_sheet.covered_component_ids
    ):
        return False
    return (
        component_id in balance_sheet.covered_component_ids
        and component_id not in balance_sheet.present_component_ids
    )


__all__ = [
    "COMPONENT_IDS",
    "POLICY_VERSION",
    "ClaimObservation",
    "ClaimDisclosure",
    "ExplicitClaimNegation",
    "OtherEnterpriseClaimsContext",
    "OtherEnterpriseClaimsError",
    "OtherEnterpriseClaimsResult",
    "ReconciledBalanceSheet",
    "BalanceSheetProof",
    "ResolvedClaimComponent",
    "resolve_other_enterprise_claims",
    "extract_reconciled_balance_sheet",
]
