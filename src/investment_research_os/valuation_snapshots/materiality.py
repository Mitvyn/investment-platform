from __future__ import annotations

from collections import defaultdict

from investment_research_os.evidence_bundles import EvidenceBundle
from investment_research_os.valuation_snapshots import (
    MarketSession,
    MaterialityAssessment,
)
from investment_research_os.valuation_snapshots.composite import MaterialityInput


MATERIALITY_POLICY_VERSION = "biotech-market-materiality-v1"

_MATERIAL_ELIGIBILITY_DOMAINS = {
    "operating_company": ("management", "risk"),
    "active_therapeutic_program": ("clinical",),
    "defined_clinical_or_regulatory_catalyst": (
        "catalyst",
        "clinical",
        "regulatory",
    ),
}

_NON_MATERIAL_ELIGIBILITY_RULES = frozenset(
    {
        "security_identity_verified",
        "us_listing",
        "cik_match",
        "common_equity",
        "therapeutics_classification",
        "required_primary_source_coverage",
    }
)

_CAPITAL_METRIC_KEYS = frozenset(
    {
        "basic_shares_outstanding",
        "option_shares_outstanding",
        "warrant_shares_outstanding",
        "convertible_share_equivalents",
        "rsu_shares_outstanding",
        "preferred_shares_outstanding",
        "cash_and_cash_equivalents",
        "restricted_cash",
        "debt_total",
        "other_enterprise_claims",
        "other_enterprise_claim:redeemable_preferred_claim",
        "other_enterprise_claim:noncontrolling_interest_claim",
        "other_enterprise_claim:royalty_monetization_liability",
        "other_enterprise_claim:contingent_consideration_claim",
        "other_enterprise_claim:pension_underfunded_claim",
        "other_enterprise_claim:finance_lease_claim",
        "atm_capacity",
        "share_count_growth",
        "basic_share_growth",
    }
)

_MATERIAL_RISK_SEVERITIES = frozenset({"medium", "high", "critical", "material"})


class FrozenEvidenceMaterialityPort:
    """Classifies only explicit, frozen evidence semantics; ambiguity stays visible."""

    policy_version = MATERIALITY_POLICY_VERSION

    def assess(
        self,
        bundle: EvidenceBundle,
        session: MarketSession,
    ) -> MaterialityInput:
        del session
        material_domains: dict[str, set[str]] = defaultdict(set)
        non_material_reasons: dict[str, str] = {}

        for catalyst in bundle.catalysts:
            for evidence_id in (
                catalyst.snapshot_id,
                *catalyst.supporting_evidence_ids,
            ):
                material_domains[evidence_id].update(("catalyst", catalyst.basis))

        for metric in bundle.metrics:
            evidence_ids = (metric.snapshot_id, *metric.supporting_evidence_ids)
            if metric.metric_key in _CAPITAL_METRIC_KEYS:
                for evidence_id in evidence_ids:
                    material_domains[evidence_id].update(
                        ("financing", "dilution", "valuation")
                    )

        for risk in bundle.risks:
            evidence_ids = (risk.snapshot_id, *risk.supporting_evidence_ids)
            if risk.severity.lower() in _MATERIAL_RISK_SEVERITIES:
                for evidence_id in evidence_ids:
                    material_domains[evidence_id].update(("risk",))
            elif risk.severity.lower() == "informational":
                for evidence_id in evidence_ids:
                    non_material_reasons.setdefault(
                        evidence_id,
                        "structured_informational_risk",
                    )

        for check in bundle.eligibility.checks:
            evidence_id = check.evidence_reference
            if evidence_id is None:
                continue
            domains = _MATERIAL_ELIGIBILITY_DOMAINS.get(check.rule_id)
            if domains is not None:
                material_domains[evidence_id].update(domains)
            elif check.rule_id in _NON_MATERIAL_ELIGIBILITY_RULES:
                non_material_reasons.setdefault(
                    evidence_id,
                    f"eligibility_{check.rule_id}_context",
                )

        assessments = tuple(
            self._assessment(
                item,
                material_domains.get(item.evidence_id),
                non_material_reasons.get(item.evidence_id),
            )
            for item in bundle.manifest
        )
        return MaterialityInput(
            assessments=assessments,
            policy_version=self.policy_version,
        )

    def _assessment(
        self,
        item,
        material_domains: set[str] | None,
        non_material_reason: str | None,
    ) -> MaterialityAssessment:
        if item.publication_at is None:
            market_materiality = "indeterminate"
            reason_code = "publication_time_unresolved"
            domains: tuple[str, ...] = ()
        elif material_domains:
            market_materiality = "material"
            reason_code = "structured_thesis_critical_evidence"
            domains = tuple(sorted(material_domains))
        elif non_material_reason is not None:
            market_materiality = "non_material"
            reason_code = non_material_reason
            domains = ()
        else:
            market_materiality = "indeterminate"
            reason_code = "materiality_not_classified"
            domains = ()
        return MaterialityAssessment(
            evidence_id=item.evidence_id,
            publication_at=item.publication_at,
            market_materiality=market_materiality,
            materiality_reason_code=reason_code,
            affected_domains=domains,
            policy_version=self.policy_version,
        )


__all__ = ["FrozenEvidenceMaterialityPort", "MATERIALITY_POLICY_VERSION"]
