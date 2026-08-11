from __future__ import annotations

from datetime import UTC, datetime, time

from workers.official_sources.models import OfficialSourceSnapshot
from workers.sec.documents import SecFilingDocumentSnapshot
from workers.sec.exhibits import SecFilingExhibitSnapshot
from workers.sec.passages import SecExactPassageResult
from workers.sec.selection import (
    SEC_FILING_POLICY_VERSION,
    SecFilingSelection,
)
from workers.sec.submissions import SecSubmissionsSnapshot
from workers.sec.submissions import (
    SEC_ISSUER_IDENTITY_POLICY_VERSION,
    evaluate_sec_issuer_identity,
)

from .companyfacts import (
    SecCompanyFactsSnapshot,
    companyfacts_basic_share_growth_passages,
    companyfacts_pipeline_inputs,
)
from .financing import (
    FinancingFieldEvidence,
    FinancingSemanticError,
    NormalizedFinancingFact,
    build_financing_semantic_matrix,
    financing_missing_field_reason_codes,
    financing_matrix_to_normalized_facts,
)
from .models import PrimarySourceRequest
from .pipeline import (
    NormalizedMetricFact,
    PrimaryEvidencePassage,
    PrimarySourceCoverageProof,
    PrimarySourcePipelineError,
)
from .regulatory_linkage import has_programme_designation_link


_OFFICIAL_COVERAGE = {
    "issuer": frozenset({"issuer_pipeline"}),
    "regulatory": frozenset({"us_regulatory"}),
}
_OFFICIAL_POLICY_VERSION = {
    "issuer": "official-issuer-source-v1",
    "regulatory": "fda-regulatory-source-v2",
}
_OFFICIAL_ORIGIN_POLICY_VERSION = {
    "issuer": "official-issuer-origin-v1",
    "regulatory": "fda-origin-v1",
}
_SEC_EXHIBIT_POLICY_VERSION = "sec-html-exhibits-v1"
_FINANCING_POLICY_VERSION = "biotech-financing-share-capital-v1"


def _regulatory_linked_source_keys(
    snapshot: OfficialSourceSnapshot,
    program_names: tuple[str, ...],
) -> frozenset[str]:
    if snapshot.source_class != "regulatory":
        if program_names:
            raise PrimarySourcePipelineError(
                "regulatory programme names require regulatory source"
            )
        return frozenset()
    normalized_names = tuple(
        dict.fromkeys(name.strip().casefold() for name in program_names if name.strip())
    )
    if not normalized_names:
        raise PrimarySourcePipelineError(
            "regulatory programme linkage requires programme names"
        )
    linked = set()
    for result in snapshot.source_results:
        if result.state != "available":
            continue
        if has_programme_designation_link(
            text_groups=(tuple(passage.passage_text for passage in result.passages),),
            program_names=normalized_names,
        ):
            linked.add(result.source_key)
    return frozenset(linked)


def _date_availability(
    published_at: datetime | None,
    publication_date,
) -> datetime:
    if published_at is not None:
        if published_at.tzinfo is None or published_at.utcoffset() is None:
            raise PrimarySourcePipelineError(
                "source publication time must include timezone"
            )
        return published_at.astimezone(UTC)
    if publication_date is None:
        raise PrimarySourcePipelineError(
            "source publication availability is unavailable"
        )
    return datetime.combine(publication_date, time.max, tzinfo=UTC)


def official_snapshot_pipeline_inputs(
    snapshot: OfficialSourceSnapshot,
    *,
    regulatory_program_names: tuple[str, ...] = (),
) -> tuple[PrimaryEvidencePassage, ...]:
    permitted_coverage = _OFFICIAL_COVERAGE.get(snapshot.source_class)
    if permitted_coverage is None:
        raise PrimarySourcePipelineError("official source class is unsupported")
    completed_requirements = {
        result.requirement_id
        for result in snapshot.coverage_results
        if result.state == "complete"
    }
    linked_regulatory_sources = _regulatory_linked_source_keys(
        snapshot,
        regulatory_program_names,
    )
    passages: list[PrimaryEvidencePassage] = []
    for result in snapshot.source_results:
        if result.state != "available":
            continue
        if result.document is None:
            raise PrimarySourcePipelineError("available official source lacks document")
        document = result.document
        if document.source_class != snapshot.source_class:
            raise PrimarySourcePipelineError(
                "official source class does not match snapshot"
            )
        coverage_keys = (
            frozenset({result.requirement_id})
            if (
                result.requirement_id in completed_requirements
                and result.requirement_id in permitted_coverage
                and (
                    snapshot.source_class != "regulatory"
                    or result.source_key in linked_regulatory_sources
                )
            )
            else frozenset()
        )
        available_at = _date_availability(
            document.published_at,
            document.publication_date,
        )
        effective_at = (
            datetime.combine(
                document.effective_date,
                time.min,
                tzinfo=UTC,
            )
            if document.effective_date is not None
            else None
        )
        for passage in result.passages:
            if passage.document_id != document.document_id:
                raise PrimarySourcePipelineError(
                    "official passage document identity mismatch"
                )
            passages.append(
                PrimaryEvidencePassage(
                    reference_key=(
                        f"{snapshot.source_class}:{result.source_key}:"
                        f"{passage.passage_key}"
                    ),
                    source_class=snapshot.source_class,
                    coverage_keys=coverage_keys,
                    source_locator=passage.locator,
                    canonical_url=document.final_url,
                    publication_at=document.published_at,
                    retrieved_at=document.retrieved_at,
                    effective_at=effective_at,
                    filing_period_start=None,
                    filing_period_end=None,
                    document_content_hash=document.content_sha256,
                    passage_text=passage.passage_text,
                    freshness="current",
                    available_at=available_at,
                    origin_policy_version=_OFFICIAL_ORIGIN_POLICY_VERSION[
                        snapshot.source_class
                    ],
                )
            )
    return tuple(sorted(passages, key=lambda passage: passage.reference_key))


def official_snapshot_coverage_proofs(
    snapshot: OfficialSourceSnapshot,
    *,
    regulatory_program_names: tuple[str, ...] = (),
):
    from .pipeline import PrimarySourceCoverageProof

    permitted_coverage = _OFFICIAL_COVERAGE.get(snapshot.source_class)
    if permitted_coverage is None:
        raise PrimarySourcePipelineError("official source class is unsupported")
    results_by_requirement = {
        requirement_id: tuple(
            result
            for result in snapshot.source_results
            if result.requirement_id == requirement_id
        )
        for requirement_id in permitted_coverage
    }
    linked_regulatory_sources = _regulatory_linked_source_keys(
        snapshot,
        regulatory_program_names,
    )
    proofs: list[PrimarySourceCoverageProof] = []
    for coverage in snapshot.coverage_results:
        if coverage.requirement_id not in permitted_coverage:
            raise PrimarySourcePipelineError(
                "official coverage requirement is unsupported"
            )
        references = tuple(
            sorted(
                (f"{snapshot.source_class}:{result.source_key}:{passage.passage_key}")
                for result in results_by_requirement[coverage.requirement_id]
                if result.state == "available"
                and (
                    snapshot.source_class != "regulatory"
                    or result.source_key in linked_regulatory_sources
                )
                for passage in result.passages
            )
        )
        linkage_complete = snapshot.source_class != "regulatory" or bool(
            linked_regulatory_sources
        )
        proofs.append(
            PrimarySourceCoverageProof(
                requirement_id=coverage.requirement_id,
                source_class=snapshot.source_class,
                policy_version=_OFFICIAL_POLICY_VERSION[snapshot.source_class],
                state=(
                    "complete"
                    if coverage.state == "complete" and linkage_complete
                    else "incomplete"
                ),
                reason_codes=(
                    ("regulatory_programme_linkage_unresolved",)
                    if coverage.state == "complete" and not linkage_complete
                    else (
                        coverage.reason_codes
                        or (
                            f"{snapshot.source_class}_"
                            f"{coverage.requirement_id}_complete",
                        )
                    )
                ),
                evidence_reference_keys=references,
            )
        )
    return tuple(sorted(proofs, key=lambda proof: proof.requirement_id))


def _validate_sec_chain(
    request: PrimarySourceRequest,
    *,
    submissions: SecSubmissionsSnapshot,
    selection: SecFilingSelection,
    documents: SecFilingDocumentSnapshot,
    exhibits: SecFilingExhibitSnapshot,
) -> None:
    identity = (
        request.operator_id,
        request.security_id,
        request.cik,
        request.as_of_cutoff,
    )
    if (
        (
            submissions.operator_id,
            submissions.security_id,
            submissions.cik,
            submissions.as_of_cutoff,
        )
        != identity
        or (
            selection.operator_id,
            selection.security_id,
            selection.cik,
            selection.as_of_cutoff,
        )
        != identity
        or (
            documents.operator_id,
            documents.security_id,
            documents.cik,
            documents.as_of_cutoff,
        )
        != identity
        or (
            exhibits.operator_id,
            exhibits.security_id,
            exhibits.cik,
            exhibits.as_of_cutoff,
        )
        != identity
    ):
        raise PrimarySourcePipelineError(
            "SEC source chain identity does not match request"
        )
    expected_submissions_url = f"https://data.sec.gov/submissions/CIK{request.cik}.json"
    if submissions.source_url != expected_submissions_url:
        raise PrimarySourcePipelineError("SEC submissions source URL is not canonical")
    if (
        submissions.issuer_name != request.issuer_name
        or submissions.identity_evidence.policy_version
        != SEC_ISSUER_IDENTITY_POLICY_VERSION
        or submissions.identity_evidence
        != evaluate_sec_issuer_identity(
            request.issuer_name,
            submissions.sec_issuer_name,
            submissions.identity_evidence.former_names,
        )
    ):
        raise PrimarySourcePipelineError("SEC issuer identity evidence is invalid")
    if selection.policy_version != SEC_FILING_POLICY_VERSION:
        raise PrimarySourcePipelineError("SEC filing selection policy is invalid")
    if documents.policy_version != selection.policy_version:
        raise PrimarySourcePipelineError("SEC document policy does not match selection")
    if exhibits.policy_version != _SEC_EXHIBIT_POLICY_VERSION:
        raise PrimarySourcePipelineError("SEC exhibit policy is invalid")
    selected_accessions = {
        filing.accession_number for filing in selection.selected_filings
    }
    document_accessions = {
        document.accession_number for document in documents.documents
    }
    if selected_accessions != document_accessions:
        raise PrimarySourcePipelineError("SEC documents do not match selected filings")
    if any(
        reference.accession_number not in selected_accessions
        for reference in exhibits.references
    ) or any(
        exhibit.accession_number not in selected_accessions
        for exhibit in exhibits.exhibits
    ):
        raise PrimarySourcePipelineError("SEC exhibit does not match selected filings")


def _material_unsupported_exhibits(
    exhibits: SecFilingExhibitSnapshot,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            reference.source_url
            for reference in exhibits.references
            if reference.collection_state == "unsupported_media"
            and not reference.exhibit_type.startswith("EX-101")
        )
    )


def _requirement_accessions(
    selection: SecFilingSelection,
    *requirement_ids: str,
) -> set[str]:
    return {
        accession
        for requirement in selection.requirement_results
        if requirement.requirement_id in requirement_ids
        for accession in requirement.selected_accessions
    }


def _matching_sec_source(
    result: SecExactPassageResult,
    documents: SecFilingDocumentSnapshot,
    exhibits: SecFilingExhibitSnapshot,
):
    sources = (*documents.documents, *exhibits.exhibits)
    matches = tuple(
        source
        for source in sources
        if (
            source.accession_number == result.accession_number
            and source.document_name == result.document_name
            and source.source_class == result.source_class
            and source.source_url == result.source_url
            and source.content_sha256 == result.source_content_sha256
            and source.retrieved_at == result.retrieved_at
            and source.published_at == result.published_at
            and source.publication_date == result.publication_date
        )
    )
    if len(matches) != 1:
        raise PrimarySourcePipelineError(
            "SEC passage provenance does not match collected source"
        )
    return matches[0]


def _validate_sec_primary_passage(
    passage: PrimaryEvidencePassage,
    documents: SecFilingDocumentSnapshot,
    exhibits: SecFilingExhibitSnapshot,
    *,
    expected_coverage: frozenset[str],
) -> None:
    matches = tuple(
        source
        for source in (*documents.documents, *exhibits.exhibits)
        if (
            passage.source_locator.startswith(
                f"{source.accession_number}/{source.document_name}#"
            )
            and source.source_url == passage.canonical_url
            and source.content_sha256 == passage.document_content_hash
            and source.retrieved_at == passage.retrieved_at
            and source.published_at == passage.publication_at
        )
    )
    if (
        passage.source_class != "sec"
        or passage.origin_policy_version != "sec-origin-v1"
        or passage.coverage_keys != expected_coverage
        or len(matches) != 1
    ):
        raise PrimarySourcePipelineError(
            "SEC passage provenance does not match collected source"
        )


def sec_passage_pipeline_input(
    request: PrimarySourceRequest,
    result: SecExactPassageResult,
    *,
    reference_key: str,
    submissions: SecSubmissionsSnapshot,
    selection: SecFilingSelection,
    documents: SecFilingDocumentSnapshot,
    exhibits: SecFilingExhibitSnapshot,
) -> PrimaryEvidencePassage:
    _validate_sec_chain(
        request,
        submissions=submissions,
        selection=selection,
        documents=documents,
        exhibits=exhibits,
    )
    if (
        result.operator_id != request.operator_id
        or result.security_id != request.security_id
        or result.cik != request.cik
    ):
        raise PrimarySourcePipelineError("SEC passage identity does not match request")
    if result.state != "found" or result.passage_text is None or result.locator is None:
        raise PrimarySourcePipelineError(
            f"SEC passage is not usable: {result.reason_code}"
        )
    _matching_sec_source(result, documents, exhibits)
    coverage_keys: set[str] = set()
    if submissions.identity_evidence.state == "verified":
        coverage_keys.add("sec_issuer_security")
    if (
        submissions.submission_history_complete
        and selection.coverage_state == "complete"
        and "required_sec_filings" in selection.eligibility_coverage
        and not _material_unsupported_exhibits(exhibits)
    ):
        coverage_keys.add("required_sec_filings")
    available_at = _date_availability(
        result.published_at,
        result.publication_date,
    )
    return PrimaryEvidencePassage(
        reference_key=reference_key,
        source_class="sec",
        coverage_keys=frozenset(coverage_keys),
        source_locator=(
            f"{result.accession_number}/{result.document_name}#{result.locator}"
        ),
        canonical_url=result.source_url,
        publication_at=result.published_at,
        retrieved_at=result.retrieved_at,
        effective_at=None,
        filing_period_start=None,
        filing_period_end=None,
        document_content_hash=result.source_content_sha256,
        passage_text=result.passage_text,
        freshness="current",
        available_at=available_at,
        origin_policy_version="sec-origin-v1",
    )


def sec_snapshot_coverage_proofs(
    request: PrimarySourceRequest,
    *,
    submissions: SecSubmissionsSnapshot,
    selection: SecFilingSelection,
    documents: SecFilingDocumentSnapshot,
    exhibits: SecFilingExhibitSnapshot,
    passages: tuple[PrimaryEvidencePassage, ...],
) -> tuple[PrimarySourceCoverageProof, ...]:
    _validate_sec_chain(
        request,
        submissions=submissions,
        selection=selection,
        documents=documents,
        exhibits=exhibits,
    )
    expected_coverage: set[str] = set()
    if submissions.identity_evidence.state == "verified":
        expected_coverage.add("sec_issuer_security")
    if (
        submissions.submission_history_complete
        and selection.coverage_state == "complete"
        and "required_sec_filings" in selection.eligibility_coverage
        and not _material_unsupported_exhibits(exhibits)
    ):
        expected_coverage.add("required_sec_filings")
    for passage in passages:
        _validate_sec_primary_passage(
            passage,
            documents,
            exhibits,
            expected_coverage=frozenset(expected_coverage),
        )
    identity_references = tuple(
        passage.reference_key
        for passage in passages
        if "sec_issuer_security" in passage.coverage_keys
    )
    required_references = tuple(
        passage.reference_key
        for passage in passages
        if "required_sec_filings" in passage.coverage_keys
    )
    unsupported = _material_unsupported_exhibits(exhibits)
    if unsupported:
        required_state = "indeterminate"
        required_reasons = ("sec_material_exhibit_unsupported_media",)
    elif (
        submissions.submission_history_complete
        and selection.coverage_state == "complete"
        and required_references
    ):
        required_state = "complete"
        required_reasons = selection.reason_codes
    elif selection.coverage_state == "indeterminate":
        required_state = "indeterminate"
        required_reasons = selection.reason_codes
    else:
        required_state = "incomplete"
        required_reasons = (
            *selection.reason_codes,
            "sec_required_filing_passage_missing",
        )
    return (
        PrimarySourceCoverageProof(
            requirement_id="required_sec_filings",
            source_class="sec",
            policy_version=selection.policy_version,
            state=required_state,
            reason_codes=required_reasons,
            evidence_reference_keys=required_references,
        ),
        PrimarySourceCoverageProof(
            requirement_id="sec_issuer_security",
            source_class="sec",
            policy_version=SEC_ISSUER_IDENTITY_POLICY_VERSION,
            state="complete" if identity_references else "incomplete",
            reason_codes=(
                (submissions.identity_evidence.reason_code,)
                if identity_references
                else (
                    ("sec_identity_passage_missing",)
                    if submissions.identity_evidence.state == "verified"
                    else (submissions.identity_evidence.reason_code,)
                )
            ),
            evidence_reference_keys=identity_references,
        ),
    )


def sec_financing_passage_pipeline_input(
    request: PrimarySourceRequest,
    result: SecExactPassageResult,
    *,
    reference_key: str,
    submissions: SecSubmissionsSnapshot,
    selection: SecFilingSelection,
    documents: SecFilingDocumentSnapshot,
    exhibits: SecFilingExhibitSnapshot,
) -> PrimaryEvidencePassage:
    _validate_sec_chain(
        request,
        submissions=submissions,
        selection=selection,
        documents=documents,
        exhibits=exhibits,
    )
    if (
        result.operator_id != request.operator_id
        or result.security_id != request.security_id
        or result.cik != request.cik
    ):
        raise PrimarySourcePipelineError(
            "SEC financing passage identity does not match request"
        )
    if result.state != "found" or result.passage_text is None or result.locator is None:
        raise PrimarySourcePipelineError(
            f"SEC financing passage is not usable: {result.reason_code}"
        )
    _matching_sec_source(result, documents, exhibits)
    permitted_accessions = _requirement_accessions(
        selection,
        "sec_latest_annual_report",
        "sec_latest_periodic_report",
        "sec_financing_filing_scan",
    )
    if result.accession_number not in permitted_accessions:
        raise PrimarySourcePipelineError(
            "SEC financing passage is outside verified filing scan"
        )
    available_at = _date_availability(
        result.published_at,
        result.publication_date,
    )
    return PrimaryEvidencePassage(
        reference_key=reference_key,
        source_class="financing",
        coverage_keys=frozenset(),
        source_locator=(
            f"{result.accession_number}/{result.document_name}#{result.locator}"
        ),
        canonical_url=result.source_url,
        publication_at=result.published_at,
        retrieved_at=result.retrieved_at,
        effective_at=None,
        filing_period_start=None,
        filing_period_end=None,
        document_content_hash=result.source_content_sha256,
        passage_text=result.passage_text,
        freshness="current",
        available_at=available_at,
        origin_policy_version="sec-origin-v1",
    )


def sec_financing_coverage_inputs(
    request: PrimarySourceRequest,
    *,
    companyfacts: SecCompanyFactsSnapshot,
    submissions: SecSubmissionsSnapshot,
    selection: SecFilingSelection,
    documents: SecFilingDocumentSnapshot,
    exhibits: SecFilingExhibitSnapshot,
    core_passages: tuple[PrimaryEvidencePassage, ...],
    core_metrics: tuple[NormalizedMetricFact, ...] = (),
    filing_passages: tuple[PrimaryEvidencePassage, ...] = (),
    calculation_passages: tuple[PrimaryEvidencePassage, ...] | None = None,
    filing_metrics: tuple[NormalizedMetricFact, ...] = (),
    field_evidence: tuple[FinancingFieldEvidence, ...] = (),
    additional_reason_codes: tuple[str, ...] = (),
) -> tuple[
    tuple[PrimaryEvidencePassage, ...],
    PrimarySourceCoverageProof,
    tuple[NormalizedFinancingFact, ...],
]:
    _validate_sec_chain(
        request,
        submissions=submissions,
        selection=selection,
        documents=documents,
        exhibits=exhibits,
    )
    if (
        companyfacts.operator_id != request.operator_id
        or companyfacts.security_id != request.security_id
        or companyfacts.cik != request.cik
        or companyfacts.issuer_name != request.issuer_name
        or companyfacts.as_of_cutoff != request.as_of_cutoff
    ):
        raise PrimarySourcePipelineError(
            "SEC Company Facts identity does not match request"
        )
    expected_companyfacts_url = (
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{request.cik}.json"
    )
    if companyfacts.source_url != expected_companyfacts_url:
        raise PrimarySourcePipelineError(
            "SEC Company Facts source URL is not canonical"
        )
    expected_core_passages, expected_core_metrics = companyfacts_pipeline_inputs(
        companyfacts
    )
    if core_passages != expected_core_passages:
        raise PrimarySourcePipelineError(
            "SEC Company Facts passages do not match snapshot"
        )
    if core_metrics != expected_core_metrics:
        raise PrimarySourcePipelineError(
            "SEC Company Facts metrics do not match snapshot"
        )
    normalized_calculation_passages = calculation_passages or ()
    if calculation_passages is not None:
        expected_calculation_passages = companyfacts_basic_share_growth_passages(
            companyfacts
        )
        if calculation_passages != expected_calculation_passages:
            raise PrimarySourcePipelineError(
                "SEC Company Facts calculation passages do not match snapshot"
            )
    if any(not reason_code.strip() for reason_code in additional_reason_codes):
        raise PrimarySourcePipelineError("financing additional reason code is invalid")
    scan = next(
        (
            result
            for result in selection.requirement_results
            if result.requirement_id == "sec_financing_filing_scan"
        ),
        None,
    )
    if scan is None:
        raise PrimarySourcePipelineError("SEC financing filing scan is missing")
    financing_accessions = set(scan.selected_accessions)
    capital_structure_accessions = _requirement_accessions(
        selection,
        "sec_latest_annual_report",
        "sec_latest_periodic_report",
    )
    filing_accessions: set[str] = set()
    collected_sources = (*documents.documents, *exhibits.exhibits)
    for passage in filing_passages:
        locator_parts = passage.source_locator.split("/", 1)
        accession = locator_parts[0] if len(locator_parts) == 2 else ""
        matches = tuple(
            source
            for source in collected_sources
            if (
                source.accession_number == accession
                and source.source_url == passage.canonical_url
                and source.content_sha256 == passage.document_content_hash
                and source.retrieved_at == passage.retrieved_at
                and source.published_at == passage.publication_at
            )
        )
        if (
            passage.source_class != "financing"
            or passage.origin_policy_version != "sec-origin-v1"
            or passage.coverage_keys
            or len(matches) != 1
        ):
            raise PrimarySourcePipelineError("SEC financing filing passage is invalid")
        filing_accessions.add(accession)
    blocking_unsupported = tuple(
        reference
        for reference in exhibits.references
        if reference.accession_number
        in (financing_accessions | capital_structure_accessions)
        and reference.collection_state == "unsupported_media"
        and not reference.exhibit_type.startswith("EX-101")
    )
    semantic_complete = False
    semantic_facts: tuple[NormalizedFinancingFact, ...] = ()
    semantic_reason_codes: tuple[str, ...]
    missing_field_reasons = financing_missing_field_reason_codes(field_evidence)
    if missing_field_reasons:
        semantic_reason_codes = (
            (
                "financing_semantic_matrix_missing"
                if not field_evidence
                else "financing_semantic_matrix_incomplete"
            ),
            *missing_field_reasons,
        )
    else:
        try:
            semantic_matrix = build_financing_semantic_matrix(
                field_evidence=field_evidence,
                passages=(
                    *core_passages,
                    *normalized_calculation_passages,
                    *filing_passages,
                ),
                metrics=(*core_metrics, *filing_metrics),
            )
        except FinancingSemanticError:
            semantic_reason_codes = ("financing_semantic_matrix_invalid",)
        else:
            semantic_facts = financing_matrix_to_normalized_facts(semantic_matrix)
            semantic_complete = semantic_matrix.coverage_state == "complete" and all(
                fact.metric_reference_key is not None for fact in semantic_facts
            )
            semantic_reason_codes = (
                semantic_matrix.reason_codes
                if semantic_complete
                else ("financing_normalized_field_facts_missing",)
            )
    complete = (
        companyfacts.coverage_state == "complete"
        and scan.state == "satisfied"
        and bool(filing_accessions & capital_structure_accessions)
        and financing_accessions <= filing_accessions
        and not blocking_unsupported
        and semantic_complete
        and not additional_reason_codes
    )
    combined = tuple(
        sorted(
            (*core_passages, *normalized_calculation_passages, *filing_passages),
            key=lambda passage: passage.reference_key,
        )
    )
    if complete:
        combined = tuple(
            PrimaryEvidencePassage(
                reference_key=passage.reference_key,
                source_class=passage.source_class,
                coverage_keys=frozenset({"financing_share_capital"}),
                source_locator=passage.source_locator,
                canonical_url=passage.canonical_url,
                publication_at=passage.publication_at,
                retrieved_at=passage.retrieved_at,
                effective_at=passage.effective_at,
                filing_period_start=passage.filing_period_start,
                filing_period_end=passage.filing_period_end,
                document_content_hash=passage.document_content_hash,
                passage_text=passage.passage_text,
                freshness=passage.freshness,
                available_at=passage.available_at,
                origin_policy_version=passage.origin_policy_version,
            )
            for passage in combined
        )
        reasons = ("financing_share_capital_complete",)
        state = "complete"
    else:
        state = (
            "indeterminate"
            if blocking_unsupported or scan.state == "indeterminate"
            else "incomplete"
        )
        reasons = tuple(
            dict.fromkeys(
                (
                    *companyfacts.reason_codes,
                    *(
                        ("sec_financing_exhibit_unsupported_media",)
                        if blocking_unsupported
                        else ()
                    ),
                    *(
                        ("sec_financing_filing_passage_missing",)
                        if financing_accessions - filing_accessions
                        else ()
                    ),
                    *(
                        ("sec_capital_structure_passage_missing",)
                        if not (filing_accessions & capital_structure_accessions)
                        else ()
                    ),
                    *((scan.reason_code,) if scan.state != "satisfied" else ()),
                    *semantic_reason_codes,
                    *additional_reason_codes,
                    "financing_share_capital_incomplete",
                )
            )
        )
    proof = PrimarySourceCoverageProof(
        requirement_id="financing_share_capital",
        source_class="financing",
        policy_version=_FINANCING_POLICY_VERSION,
        state=state,
        reason_codes=reasons,
        evidence_reference_keys=tuple(passage.reference_key for passage in combined),
    )
    return combined, proof, semantic_facts


__all__ = [
    "official_snapshot_coverage_proofs",
    "official_snapshot_pipeline_inputs",
    "sec_financing_coverage_inputs",
    "sec_financing_passage_pipeline_input",
    "sec_passage_pipeline_input",
    "sec_snapshot_coverage_proofs",
]
