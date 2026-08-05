from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from workers.clinical_trials.collector import ClinicalTrialsSnapshot
from workers.official_sources.models import OfficialSourceSnapshot
from workers.sec.submissions import SecSubmissionsSnapshot
from workers.security_registry.models import RegisteredSecurity

from .companyfacts import SecCompanyFactsSnapshot
from .models import PrimarySourceRequest
from .pipeline import PrimaryEvidencePassage


ELIGIBILITY_SOURCE_POLICY_VERSION = "biotech-eligibility-sources-v1"
ELIGIBILITY_RULE_IDS = (
    "security_identity_verified",
    "us_listing",
    "cik_match",
    "common_equity",
    "operating_company",
    "therapeutics_classification",
    "active_therapeutic_program",
    "defined_clinical_or_regulatory_catalyst",
    "required_primary_source_coverage",
)
_US_EXCHANGES = frozenset(
    {"nasdaq", "nyse", "nyse american", "nasdaq global select market"}
)
_ACTIVE_TRIAL_STATUSES = frozenset(
    {
        "RECRUITING",
        "NOT_YET_RECRUITING",
        "ACTIVE_NOT_RECRUITING",
        "ENROLLING_BY_INVITATION",
    }
)
_THERAPEUTIC_INTERVENTION_TYPES = frozenset({"DRUG", "BIOLOGICAL", "GENETIC"})
_REQUIRED_COVERAGE = frozenset(
    {
        "sec_issuer_security",
        "required_sec_filings",
        "issuer_pipeline",
        "authoritative_trial",
        "us_regulatory",
        "financing_share_capital",
    }
)
_REQUIRED_COMPANYFACT_KEYS = frozenset(
    {
        "basic_shares_outstanding",
        "cash_and_cash_equivalents",
        "debt_current",
        "operating_cash_used",
    }
)
_COMMON_EQUITY_LISTING_PATTERN = re.compile(
    r"\b(?:our common stock|shares of (?:our|the registrant's) common stock)"
    r"\s+(?:is|are)\s+listed on\b",
    re.IGNORECASE,
)


class EligibilitySourceError(ValueError):
    """Raised when eligibility sources do not belong to one request."""


@dataclass(frozen=True, slots=True)
class EligibilityRuleSourceOutcome:
    rule_id: str
    rule_version: str
    state: str
    reason_code: str
    evidence_reference_keys: tuple[str, ...]
    normalized_values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DerivedEligibilityProfile:
    policy_version: str
    display_symbol: str
    primary_listing_country: str
    security_type: str
    issuer_status: str
    therapeutics_classification: str
    active_therapeutic_programs: tuple[str, ...]
    outcomes: tuple[EligibilityRuleSourceOutcome, ...]

    @property
    def eligible(self) -> bool:
        return all(outcome.state == "pass" for outcome in self.outcomes)

    @property
    def security_identity_verified(self) -> bool:
        return self._passed("security_identity_verified")

    @property
    def cik_matches_issuer(self) -> bool:
        return self._passed("cik_match")

    @property
    def rule_evidence(self) -> dict[str, str]:
        return {
            outcome.rule_id: outcome.evidence_reference_keys[0]
            for outcome in self.outcomes
            if outcome.state == "pass" and outcome.evidence_reference_keys
        }

    def _passed(self, rule_id: str) -> bool:
        return any(
            outcome.rule_id == rule_id and outcome.state == "pass"
            for outcome in self.outcomes
        )


def _outcome(
    rule_id: str,
    passed: bool,
    references: tuple[str, ...],
    normalized_values: tuple[str, ...],
) -> EligibilityRuleSourceOutcome:
    return EligibilityRuleSourceOutcome(
        rule_id=rule_id,
        rule_version=f"{rule_id}.source.v1",
        state="pass" if passed else "fail",
        reason_code=f"{rule_id}_{'verified' if passed else 'not_verified'}",
        evidence_reference_keys=references,
        normalized_values=normalized_values,
    )


def _references_for_coverage(
    passages: tuple[PrimaryEvidencePassage, ...],
    coverage_key: str,
) -> tuple[str, ...]:
    return tuple(
        passage.reference_key
        for passage in passages
        if coverage_key in passage.coverage_keys
    )


def _normalized_issuer_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("&", " and ")
    return " ".join(re.sub(r"[^\w]+", " ", normalized).split())


def derive_biotech_eligibility_profile(
    *,
    request: PrimarySourceRequest,
    registered_security: RegisteredSecurity,
    submissions: SecSubmissionsSnapshot,
    issuer: OfficialSourceSnapshot,
    clinical_trials: ClinicalTrialsSnapshot,
    companyfacts: SecCompanyFactsSnapshot,
    passages: tuple[PrimaryEvidencePassage, ...],
) -> DerivedEligibilityProfile:
    identity = (
        request.operator_id,
        request.security_id,
        request.cik,
    )
    source_identities = (
        (
            registered_security.operator_id,
            registered_security.security_id,
            registered_security.cik,
        ),
        (
            submissions.operator_id,
            submissions.security_id,
            submissions.cik,
        ),
        (
            issuer.operator_id,
            issuer.security_id,
            issuer.cik,
        ),
        (
            clinical_trials.operator_id,
            clinical_trials.security_id,
            clinical_trials.cik,
        ),
        (
            companyfacts.operator_id,
            companyfacts.security_id,
            companyfacts.cik,
        ),
    )
    source_names = (
        registered_security.issuer_name,
        submissions.issuer_name,
        issuer.issuer_name,
        clinical_trials.issuer_name,
        companyfacts.issuer_name,
    )
    if any(source_identity != identity for source_identity in source_identities) or any(
        _normalized_issuer_name(source_name)
        != _normalized_issuer_name(request.issuer_name)
        for source_name in source_names
    ):
        raise EligibilitySourceError(
            "eligibility source identity does not match request"
        )
    if (
        issuer.as_of_cutoff != request.as_of_cutoff
        or clinical_trials.as_of_cutoff != request.as_of_cutoff
        or companyfacts.as_of_cutoff != request.as_of_cutoff
        or submissions.as_of_cutoff != request.as_of_cutoff
    ):
        raise EligibilitySourceError("eligibility source cutoff does not match request")
    if (
        clinical_trials.policy_version != "clinical-trials-source-v2"
        or clinical_trials.coverage.policy_version != clinical_trials.policy_version
    ):
        raise EligibilitySourceError("clinical eligibility source policy is invalid")

    identity_references = _references_for_coverage(
        passages,
        "sec_issuer_security",
    )
    issuer_references = _references_for_coverage(
        passages,
        "issuer_pipeline",
    )
    clinical_references = _references_for_coverage(
        passages,
        "authoritative_trial",
    )
    coverage_references = tuple(
        dict.fromkeys(
            reference
            for coverage_key in sorted(_REQUIRED_COVERAGE)
            for reference in _references_for_coverage(
                passages,
                coverage_key,
            )
        )
    )

    identity_verified = (
        registered_security.source_url
        == "https://www.sec.gov/files/company_tickers_exchange.json"
        and submissions.identity_evidence.state == "verified"
        and bool(identity_references)
    )
    exchange = registered_security.primary_listing_exchange.strip().casefold()
    us_listing = (
        exchange in _US_EXCHANGES
        and request.primary_listing_exchange.strip().casefold() == exchange
    )
    cik_match = (
        registered_security.cik == submissions.cik == request.cik
        and submissions.identity_evidence.state == "verified"
    )
    common_equity_references = tuple(
        passage.reference_key
        for passage in passages
        if passage.source_class == "sec"
        and _COMMON_EQUITY_LISTING_PATTERN.search(passage.passage_text) is not None
    )
    common_equity = bool(common_equity_references)

    active_studies = tuple(
        study
        for study in clinical_trials.included_studies
        if study.valid_at_cutoff
        and study.program_associated
        and study.issuer_associated
        and study.status in _ACTIVE_TRIAL_STATUSES
    )
    active_programs = tuple(
        dict.fromkeys(study.program_name for study in active_studies)
    )
    therapeutic_studies = tuple(
        study
        for study in active_studies
        if any(
            intervention.intervention_type in _THERAPEUTIC_INTERVENTION_TYPES
            for intervention in study.interventions
        )
    )
    companyfacts_valid = (
        companyfacts.policy_version == "sec-companyfacts-core-metrics-v1"
        and companyfacts.coverage_state == "complete"
        and _REQUIRED_COMPANYFACT_KEYS
        <= frozenset(fact.metric_key for fact in companyfacts.facts)
        and companyfacts.source_url
        == (f"https://data.sec.gov/api/xbrl/companyfacts/CIK{request.cik}.json")
    )
    operating = bool(issuer_references) and companyfacts_valid and bool(active_studies)
    therapeutics = bool(issuer_references) and bool(therapeutic_studies)
    catalyst_studies = tuple(
        study for study in active_studies if study.primary_completion_date is not None
    )
    catalyst_references = tuple(
        reference
        for study in catalyst_studies
        for reference in clinical_references
        if study.nct_id in reference
    )
    clinical_coverage_valid = clinical_trials.coverage.status == "covered" and set(
        clinical_trials.coverage.included_nct_ids
    ) == {study.nct_id for study in clinical_trials.included_studies}
    coverage_complete = (
        _REQUIRED_COVERAGE
        <= frozenset(
            coverage_key
            for passage in passages
            for coverage_key in passage.coverage_keys
        )
        and companyfacts_valid
        and clinical_coverage_valid
        and issuer.coverage_state == "complete"
        and identity_verified
    )
    outcomes = (
        _outcome(
            "security_identity_verified",
            identity_verified,
            identity_references,
            ("true",) if identity_verified else ("false",),
        ),
        _outcome(
            "us_listing",
            us_listing,
            identity_references,
            (
                "US" if us_listing else "unknown",
                request.primary_listing_exchange.strip().upper(),
            ),
        ),
        _outcome(
            "cik_match",
            cik_match,
            identity_references,
            (request.cik,),
        ),
        _outcome(
            "common_equity",
            common_equity,
            common_equity_references,
            ("common_equity" if common_equity else "unknown",),
        ),
        _outcome(
            "operating_company",
            operating,
            (*issuer_references, *clinical_references),
            ("operating" if operating else "unknown",),
        ),
        _outcome(
            "therapeutics_classification",
            therapeutics,
            (*issuer_references, *clinical_references),
            ("therapeutics_biotech" if therapeutics else "unknown",),
        ),
        _outcome(
            "active_therapeutic_program",
            bool(active_programs),
            clinical_references,
            active_programs,
        ),
        _outcome(
            "defined_clinical_or_regulatory_catalyst",
            bool(catalyst_references),
            catalyst_references,
            tuple(
                (f"{study.nct_id}:primary_completion:{study.primary_completion_date}")
                for study in catalyst_studies
            ),
        ),
        _outcome(
            "required_primary_source_coverage",
            coverage_complete,
            coverage_references,
            tuple(
                sorted(
                    {
                        coverage_key
                        for passage in passages
                        for coverage_key in passage.coverage_keys
                        if coverage_key in _REQUIRED_COVERAGE
                    }
                )
            ),
        ),
    )
    return DerivedEligibilityProfile(
        policy_version=ELIGIBILITY_SOURCE_POLICY_VERSION,
        display_symbol=registered_security.ticker,
        primary_listing_country="US" if us_listing else "unknown",
        security_type="common_equity" if common_equity else "unknown",
        issuer_status="operating" if operating else "unknown",
        therapeutics_classification=(
            "therapeutics_biotech" if therapeutics else "unknown"
        ),
        active_therapeutic_programs=active_programs,
        outcomes=outcomes,
    )


__all__ = [
    "ELIGIBILITY_RULE_IDS",
    "ELIGIBILITY_SOURCE_POLICY_VERSION",
    "DerivedEligibilityProfile",
    "EligibilityRuleSourceOutcome",
    "EligibilitySourceError",
    "derive_biotech_eligibility_profile",
]
