from __future__ import annotations

from calendar import monthrange
from dataclasses import replace
from datetime import UTC, date, datetime, time
from typing import Protocol

from investment_research_os.evidence_bundles import (
    EvidenceBundleCandidate,
    EvidenceGap,
)
from investment_research_os.research_runs import ResearchRun

from workers.clinical_trials.collector import (
    clinical_trials_coverage_proof,
    clinical_trials_pipeline_inputs,
)

from .adapters import (
    official_snapshot_coverage_proofs,
    official_snapshot_pipeline_inputs,
    sec_financing_coverage_inputs,
    sec_financing_passage_pipeline_input,
    sec_passage_pipeline_input,
    sec_snapshot_coverage_proofs,
)
from .companyfacts import (
    SecCompanyFactsCollectorError,
    companyfacts_basic_share_growth_observations,
    companyfacts_basic_share_growth_passages,
    companyfacts_pipeline_inputs,
    companyfacts_other_enterprise_claim_inputs,
)
from .corporate_actions import reconcile_corporate_actions
from .eligibility import derive_biotech_eligibility_profile
from .financing import derive_financing_field_evidence
from .financing_metrics import (
    FilingFinancingMetricError,
    normalize_filing_financing_metrics,
)
from .other_enterprise_claims import (
    OtherEnterpriseClaimsError,
    extract_reconciled_balance_sheet,
)
from .models import PrimarySourceRequest
from .plans import PRIMARY_SOURCE_PLAN_V3
from .pipeline import (
    NormalizedCatalystFact,
    NormalizedMetricFact,
    NormalizedRiskFact,
    PrimaryEvidencePassage,
    PrimarySourcePipeline,
)
from .replay import replay_primary_source_capture
from .share_growth import calculate_basic_share_growth
from .storage import FilePrimarySourceCaptureRepository


class PersistedPrimarySourceEvidenceError(ValueError):
    """Raised when a Research Run cannot resolve one exact accepted capture."""


class EvidenceCandidateAssembler(Protocol):
    def assemble(
        self,
        raw_archive: bytes,
        *,
        request: PrimarySourceRequest,
        ticker: str,
        sec_user_agent: str,
        trusted_issuer_hosts: tuple[str, ...],
        accepted_at: datetime,
    ) -> EvidenceBundleCandidate: ...


def _catalyst_window(value: str) -> tuple[date, date]:
    parts = value.split("-")
    try:
        if len(parts) == 3:
            parsed = date.fromisoformat(value)
            return parsed, parsed
        if len(parts) == 2:
            year, month = (int(part) for part in parts)
            return (
                date(year, month, 1),
                date(year, month, monthrange(year, month)[1]),
            )
        if len(parts) == 1:
            year = int(parts[0])
            return date(year, 1, 1), date(year, 12, 31)
    except ValueError as error:
        raise PersistedPrimarySourceEvidenceError(
            "clinical catalyst date is invalid"
        ) from error
    raise PersistedPrimarySourceEvidenceError(
        "clinical catalyst date precision is unsupported"
    )


class ReplayEvidenceCandidateAssembler:
    """Replays one accepted archive into deterministic normalized evidence."""

    def assemble(
        self,
        raw_archive: bytes,
        *,
        request: PrimarySourceRequest,
        ticker: str,
        sec_user_agent: str,
        trusted_issuer_hosts: tuple[str, ...],
        accepted_at: datetime,
    ) -> EvidenceBundleCandidate:
        replay = replay_primary_source_capture(
            raw_archive,
            request=request,
            ticker=ticker,
            sec_user_agent=sec_user_agent,
            trusted_issuer_hosts=trusted_issuer_hosts,
            accepted_at=lambda: accepted_at,
        )
        sec_passages = []
        financing_passages = []
        corporate_action_passages = []
        for replayed in replay.sec_passages:
            if replayed.plan.role in {"financing", "corporate_action"}:
                passage = sec_financing_passage_pipeline_input(
                    request,
                    replayed.extraction,
                    reference_key=replayed.plan.reference_key,
                    submissions=replay.submissions,
                    selection=replay.selection,
                    documents=replay.documents,
                    exhibits=replay.exhibits,
                )
                if replayed.plan.role == "corporate_action":
                    corporate_action_passages.append(passage)
                else:
                    financing_passages.append(passage)
            else:
                sec_passages.append(
                    sec_passage_pipeline_input(
                        request,
                        replayed.extraction,
                        reference_key=replayed.plan.reference_key,
                        submissions=replay.submissions,
                        selection=replay.selection,
                        documents=replay.documents,
                        exhibits=replay.exhibits,
                    )
                )
        core_sec_passages = tuple(sec_passages)
        sec_proofs = sec_snapshot_coverage_proofs(
            request,
            submissions=replay.submissions,
            selection=replay.selection,
            documents=replay.documents,
            exhibits=replay.exhibits,
            passages=core_sec_passages,
        )
        issuer_passages = official_snapshot_pipeline_inputs(replay.issuer)
        issuer_proofs = official_snapshot_coverage_proofs(replay.issuer)
        clinical_passages = clinical_trials_pipeline_inputs(replay.clinical_trials)
        clinical_proof = clinical_trials_coverage_proof(replay.clinical_trials)
        regulatory_program_names = tuple(
            dict.fromkeys(
                (
                    replay.capture.plan.clinical_trial_search.program_name,
                    *replay.capture.plan.clinical_trial_search.search_terms,
                )
            )
        )
        regulatory_passages = official_snapshot_pipeline_inputs(
            replay.regulatory,
            regulatory_program_names=regulatory_program_names,
        )
        regulatory_proofs = official_snapshot_coverage_proofs(
            replay.regulatory,
            regulatory_program_names=regulatory_program_names,
        )
        companyfacts_passages, companyfacts_metrics = companyfacts_pipeline_inputs(
            replay.companyfacts
        )
        share_growth_passages = (
            companyfacts_basic_share_growth_passages(replay.companyfacts)
            if replay.capture.plan.loaded.contract_version == PRIMARY_SOURCE_PLAN_V3
            else ()
        )
        share_growth_metrics: tuple[NormalizedMetricFact, ...] = ()
        share_growth_reason_codes: tuple[str, ...] = ()
        if replay.capture.plan.loaded.contract_version == PRIMARY_SOURCE_PLAN_V3:
            observations = companyfacts_basic_share_growth_observations(
                replay.companyfacts
            )
            eligible_periods = tuple(
                sorted(
                    {
                        observation.period_end
                        for observation in observations
                        if observation.accepted_at <= request.as_of_cutoff
                    }
                )
            )
            assessment = None
            if len(eligible_periods) >= 2:
                assessment = reconcile_corporate_actions(
                    request=request,
                    passages=tuple(corporate_action_passages),
                    from_period_end=eligible_periods[-2],
                    to_period_end=eligible_periods[-1],
                )
            growth = calculate_basic_share_growth(
                observations=observations,
                as_of_cutoff=request.as_of_cutoff,
                corporate_action_reconciliation=(
                    assessment.reconciliation if assessment is not None else None
                ),
            )
            if growth.state == "complete":
                assert growth.growth_percent is not None
                share_growth_metrics = (
                    NormalizedMetricFact(
                        reference_key="financing-metric:share_growth",
                        source_class="financing",
                        metric_key="basic_share_growth",
                        value=growth.growth_percent,
                        unit=growth.unit,
                        period_start=growth.period_start,
                        period_end=growth.period_end,
                        calculation_method="derived",
                        formula=growth.formula,
                        supporting_passage_keys=growth.evidence_reference_keys,
                    ),
                )
            else:
                share_growth_reason_codes = tuple(
                    dict.fromkeys(
                        (
                            *(
                                assessment.reason_codes
                                if assessment is not None
                                else ()
                            ),
                            *growth.reason_codes,
                        )
                    )
                )
        try:
            filing_metrics = normalize_filing_financing_metrics(
                tuple(financing_passages)
            )
        except FilingFinancingMetricError:
            filing_metrics = ()
        field_evidence = derive_financing_field_evidence(
            passages=(
                *companyfacts_passages,
                *share_growth_passages,
                *financing_passages,
                *corporate_action_passages,
            ),
            metrics=(
                *companyfacts_metrics,
                *filing_metrics,
                *share_growth_metrics,
            ),
        )
        absence_metric_definitions = {
            "options": ("option_shares_outstanding", "shares"),
            "warrants": ("warrant_shares_outstanding", "shares"),
            "convertibles": ("convertible_share_equivalents", "shares"),
            "rsus": ("rsu_shares_outstanding", "shares"),
            "preferreds": ("preferred_shares_outstanding", "shares"),
            "atm_shelf_capacity": ("atm_capacity", "USD"),
            "share_growth": ("share_count_growth", "percent"),
        }
        existing_metric_references = {
            metric.reference_key
            for metric in (
                *companyfacts_metrics,
                *filing_metrics,
                *share_growth_metrics,
            )
        }
        absence_metrics = []
        normalized_field_evidence = []
        financing_passages_by_key = {
            passage.reference_key: passage for passage in financing_passages
        }
        filing_sources = (
            *replay.documents.documents,
            *replay.exhibits.exhibits,
        )
        for outcome in field_evidence:
            metric_reference = f"financing-metric:{outcome.field_id}"
            if (
                outcome.outcome != "absent"
                or outcome.field_id not in absence_metric_definitions
                or metric_reference in existing_metric_references
            ):
                normalized_field_evidence.append(outcome)
                continue
            support = next(
                (
                    financing_passages_by_key[key]
                    for key in outcome.evidence_reference_keys
                    if key in financing_passages_by_key
                ),
                None,
            )
            if support is None:
                normalized_field_evidence.append(outcome)
                continue
            accession = support.source_locator.partition("/")[0]
            period_end = next(
                (
                    getattr(source, "report_date", None)
                    for source in filing_sources
                    if (
                        source.accession_number == accession
                        and getattr(source, "report_date", None) is not None
                    )
                ),
                None,
            )
            if period_end is None:
                normalized_field_evidence.append(outcome)
                continue
            metric_key, unit = absence_metric_definitions[outcome.field_id]
            absence_metrics.append(
                NormalizedMetricFact(
                    reference_key=metric_reference,
                    source_class="financing",
                    metric_key=metric_key,
                    value="0",
                    unit=unit,
                    period_start=None,
                    period_end=period_end,
                    calculation_method="reported",
                    formula=None,
                    supporting_passage_keys=(support.reference_key,),
                )
            )
            normalized_field_evidence.append(
                type(outcome)(
                    field_id=outcome.field_id,
                    outcome=outcome.outcome,
                    evidence_reference_keys=(metric_reference,),
                )
            )
        filing_metrics = (*filing_metrics, *absence_metrics)
        field_evidence = tuple(normalized_field_evidence)
        enterprise_claim_metrics: tuple[NormalizedMetricFact, ...] = ()
        enterprise_claim_risk: NormalizedRiskFact | None = None
        balance_sheet_passage: PrimaryEvidencePassage | None = None
        try:
            balance_sheet_period = next(
                item.period_end
                for item in replay.companyfacts.facts
                if item.metric_key == "cash_and_cash_equivalents"
            )
            present_claim_ids = tuple(
                fact.metric_key.removeprefix("other_enterprise_claim:")
                for fact in replay.companyfacts.facts
                if fact.metric_key.startswith("other_enterprise_claim:")
                and fact.period_end == balance_sheet_period
            )
            balance_sheet_proof = extract_reconciled_balance_sheet(
                replay.documents.documents,
                period_end=balance_sheet_period,
                present_component_ids=present_claim_ids,
            )
            balance_sheet_passage = PrimaryEvidencePassage(
                reference_key=balance_sheet_proof.reference_key,
                source_class="financing",
                coverage_keys=frozenset(),
                source_locator=balance_sheet_proof.source_locator,
                canonical_url=balance_sheet_proof.canonical_url,
                publication_at=balance_sheet_proof.publication_at,
                retrieved_at=balance_sheet_proof.retrieved_at,
                effective_at=datetime.combine(
                    balance_sheet_period,
                    time.max,
                    tzinfo=UTC,
                ),
                filing_period_start=None,
                filing_period_end=balance_sheet_period,
                document_content_hash=balance_sheet_proof.content_hash,
                passage_text=balance_sheet_proof.passage_text,
                freshness="current",
                origin_policy_version="sec-origin-v1",
                available_at=balance_sheet_proof.publication_at,
            )
            enterprise_claim_metrics = companyfacts_other_enterprise_claim_inputs(
                replay.companyfacts,
                financing_metrics=filing_metrics,
                balance_sheet=balance_sheet_proof.balance_sheet,
            )
        except (
            OtherEnterpriseClaimsError,
            SecCompanyFactsCollectorError,
            ValueError,
        ) as error:
            reason_code = str(error)
            enterprise_claim_risk = NormalizedRiskFact(
                reference_key=f"valuation:{reason_code}",
                source_class="financing",
                title="Other enterprise claims unresolved",
                risk_type="valuation_evidence_gap",
                severity="blocking_for_valuation",
                status=reason_code,
                supporting_passage_keys=tuple(
                    f"sec-companyfacts:{fact.metric_key}"
                    for fact in replay.companyfacts.facts
                    if fact.metric_key
                    in {"cash_and_cash_equivalents", "debt_total", "debt_current"}
                )[:1],
            )
        (
            normalized_financing_passages,
            financing_proof,
            financing_facts,
        ) = sec_financing_coverage_inputs(
            request,
            companyfacts=replay.companyfacts,
            submissions=replay.submissions,
            selection=replay.selection,
            documents=replay.documents,
            exhibits=replay.exhibits,
            core_passages=companyfacts_passages,
            core_metrics=companyfacts_metrics,
            calculation_passages=(
                share_growth_passages
                if replay.capture.plan.loaded.contract_version == PRIMARY_SOURCE_PLAN_V3
                else None
            ),
            filing_passages=(
                *financing_passages,
                *corporate_action_passages,
            ),
            filing_metrics=(*filing_metrics, *share_growth_metrics),
            field_evidence=field_evidence,
            additional_reason_codes=share_growth_reason_codes,
        )
        all_passages = (
            *core_sec_passages,
            *issuer_passages,
            *clinical_passages,
            *regulatory_passages,
            *normalized_financing_passages,
            *((balance_sheet_passage,) if balance_sheet_passage is not None else ()),
        )
        catalysts = []
        for study in replay.clinical_trials.included_studies:
            if study.primary_completion_date is None:
                continue
            window_start, window_end = _catalyst_window(study.primary_completion_date)
            if window_end < request.as_of_cutoff.date():
                continue
            catalysts.append(
                NormalizedCatalystFact(
                    reference_key=(
                        f"clinical-catalyst:{study.nct_id}:primary-completion"
                    ),
                    source_class="clinical",
                    event=f"{study.brief_title} primary completion",
                    program=study.program_name,
                    basis="clinical",
                    status="expected",
                    window_start=window_start,
                    window_end=window_end,
                    supporting_passage_keys=(f"clinical-trial:{study.nct_id}",),
                )
            )
        risks = tuple(
            NormalizedRiskFact(
                reference_key=f"financing-semantic-outcome:{fact.field_id}",
                source_class="financing",
                title=f"Financing semantic outcome: {fact.field_id}",
                risk_type=f"financing_semantic:{fact.field_id}",
                severity="informational",
                status=fact.outcome,
                supporting_passage_keys=(
                    fact.supporting_passage_keys or fact.evidence_reference_keys
                ),
            )
            for fact in financing_facts
        )
        if enterprise_claim_risk is not None:
            risks = (*risks, enterprise_claim_risk)
        pipeline_result = PrimarySourcePipeline().assemble(
            request=request,
            profile=derive_biotech_eligibility_profile(
                request=request,
                registered_security=replay.registered_security,
                submissions=replay.submissions,
                issuer=replay.issuer,
                clinical_trials=replay.clinical_trials,
                companyfacts=replay.companyfacts,
                passages=all_passages,
            ),
            passages=all_passages,
            coverage_proofs=(
                *sec_proofs,
                *issuer_proofs,
                clinical_proof,
                *regulatory_proofs,
                financing_proof,
            ),
            metrics=(
                *companyfacts_metrics,
                *filing_metrics,
                *share_growth_metrics,
                *enterprise_claim_metrics,
            ),
            catalysts=tuple(catalysts),
            risks=risks,
            regulatory_program_names=regulatory_program_names,
        )
        candidate = pipeline_result.bundle_candidate
        if share_growth_reason_codes:
            candidate = replace(
                candidate,
                declared_gaps=(
                    *candidate.declared_gaps,
                    *(
                        EvidenceGap(
                            code=f"financing_{reason_code}",
                            source_class="financing",
                            blocking=True,
                            explanation=(
                                "Basic share growth remains unresolved under "
                                "frozen primary-source evidence."
                            ),
                            requirement_id="financing_share_capital",
                            reason_code=reason_code,
                        )
                        for reason_code in share_growth_reason_codes
                    ),
                ),
            )
        return candidate


class PersistedPrimarySourceEvidenceSource:
    """Run-bound accepted-capture source with no collection fallback."""

    def __init__(
        self,
        *,
        repository: FilePrimarySourceCaptureRepository,
        research_run: ResearchRun,
        assembler: EvidenceCandidateAssembler,
        sec_user_agent: str,
        trusted_issuer_hosts: tuple[str, ...],
    ) -> None:
        if not sec_user_agent.strip():
            raise PersistedPrimarySourceEvidenceError("SEC user agent is required")
        if not trusted_issuer_hosts or any(
            not host.strip() for host in trusted_issuer_hosts
        ):
            raise PersistedPrimarySourceEvidenceError(
                "trusted issuer hosts are required"
            )
        self._repository = repository
        self._run = research_run
        self._assembler = assembler
        self._sec_user_agent = sec_user_agent
        self._trusted_issuer_hosts = trusted_issuer_hosts

    def load(
        self,
        operator_id: str,
        security_id: str,
        as_of_cutoff: datetime,
    ) -> EvidenceBundleCandidate:
        cutoff = as_of_cutoff.astimezone(UTC)
        if (
            operator_id != self._run.operator_id
            or security_id != self._run.security_id
            or cutoff != self._run.as_of_cutoff
        ):
            raise PersistedPrimarySourceEvidenceError(
                "evidence request does not match Research Run"
            )
        binding = self._repository.get_for_run(
            self._run.operator_id,
            self._run.id,
        )
        if binding is None:
            raise PersistedPrimarySourceEvidenceError(
                "Research Run has no accepted capture binding"
            )
        expected_binding_identity = (
            self._run.operator_id,
            self._run.id,
            self._run.security_id,
            self._run.as_of_cutoff,
            self._run.question_type,
            self._run.question_type_version,
            self._run.workflow_config_version,
            self._run.thesis_contract_id,
        )
        binding_identity = (
            binding.operator_id,
            binding.research_run_id,
            binding.security_id,
            binding.as_of_cutoff,
            binding.question_type,
            binding.question_type_version,
            binding.workflow_config_version,
            binding.thesis_contract_id,
        )
        if binding_identity != expected_binding_identity:
            raise PersistedPrimarySourceEvidenceError(
                "accepted capture binding does not match Research Run"
            )
        metadata = self._repository.get_capture(
            binding.operator_id,
            binding.capture_id,
            binding.capture_revision,
        )
        if metadata is None:
            raise PersistedPrimarySourceEvidenceError("accepted capture is unavailable")
        binding_capture_identity = (
            binding.security_id,
            binding.as_of_cutoff,
            binding.capture_id,
            binding.capture_revision,
            binding.package_sha256,
            binding.capture_content_hash,
            binding.plan_id,
            binding.plan_revision,
            binding.plan_content_hash,
        )
        metadata_identity = (
            metadata.security_id,
            metadata.as_of_cutoff,
            metadata.capture_id,
            metadata.capture_revision,
            metadata.package_sha256,
            metadata.capture_content_hash,
            metadata.plan_id,
            metadata.plan_revision,
            metadata.plan_content_hash,
        )
        if binding_capture_identity != metadata_identity:
            raise PersistedPrimarySourceEvidenceError(
                "accepted capture metadata does not match binding"
            )
        request = PrimarySourceRequest(
            operator_id=self._run.operator_id,
            security_id=self._run.security_id,
            cik=self._run.security_identity.cik,
            issuer_name=self._run.security_identity.issuer_name,
            primary_listing_exchange=(
                self._run.security_identity.primary_listing_exchange
            ),
            as_of_cutoff=self._run.as_of_cutoff,
        )
        candidate = self._assembler.assemble(
            self._repository.read_archive(
                binding.operator_id,
                binding.capture_id,
                binding.capture_revision,
            ),
            request=request,
            ticker=self._run.security_identity.symbol,
            sec_user_agent=self._sec_user_agent,
            trusted_issuer_hosts=self._trusted_issuer_hosts,
            accepted_at=metadata.accepted_at,
        )
        if (
            candidate.security_id != self._run.security_id
            or candidate.as_of_cutoff != self._run.as_of_cutoff
            or candidate.evidence_policy_version != binding.evidence_policy_version
        ):
            raise PersistedPrimarySourceEvidenceError(
                "assembled evidence does not match Research Run"
            )
        return candidate


__all__ = [
    "EvidenceCandidateAssembler",
    "PersistedPrimarySourceEvidenceError",
    "PersistedPrimarySourceEvidenceSource",
    "ReplayEvidenceCandidateAssembler",
]
