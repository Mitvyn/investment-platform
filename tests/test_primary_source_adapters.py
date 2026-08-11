from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path
import unittest

from workers.official_sources import (
    OfficialBytesResponse,
    OfficialIssuerEvidenceAdapter,
    OfficialPassageSpec,
    OfficialSourceLocator,
)
from workers.primary_sources.adapters import (
    official_snapshot_coverage_proofs,
    official_snapshot_pipeline_inputs,
    sec_financing_coverage_inputs,
    sec_financing_passage_pipeline_input,
    sec_passage_pipeline_input,
    sec_snapshot_coverage_proofs,
)
from workers.primary_sources.companyfacts import (
    SecCompanyFactsCollector,
    SecCompanyFactsSettings,
    companyfacts_pipeline_inputs,
)
from workers.primary_sources.financing import (
    FINANCING_FIELD_IDS,
    FinancingFieldEvidence,
)
from workers.primary_sources.models import PrimarySourceRequest
from workers.primary_sources.pipeline import (
    NormalizedMetricFact,
    PrimarySourcePipelineError,
)
from workers.regulatory import FDARegulatoryEvidenceAdapter
from workers.sec.documents import (
    SecFilingDocument,
    SecFilingDocumentSnapshot,
)
from workers.sec.exhibits import (
    SecFilingExhibitReference,
    SecFilingExhibitSnapshot,
)
from workers.sec.passages import SecExactPassageExtractor
from workers.sec.selection import RequiredSecFilingSelector
from tests.test_sec_filing_selection import collected_snapshot
from tests.test_sec_passages import PASSAGE as SEC_PASSAGE
from tests.test_sec_companyfacts import (
    FIXTURE as COMPANYFACTS_FIXTURE,
)
from tests.test_sec_companyfacts import (
    FixtureTransport as CompanyFactsTransport,
)


OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
SECURITY_ID = "f594edb2-7fff-4e40-9c26-2c06bcbecb91"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)
ISSUER_URL = "https://investors.example-biotech.com/news/programme-update.html"
ISSUER_PASSAGE = (
    "The Phase 2 study remains active and topline data are expected "
    "in the fourth quarter of 2026."
)
FINANCING_SEMANTIC_PASSAGE = (
    "The company reported basic shares, no stock options, no warrants, "
    "no convertible securities, no restricted stock units, no preferred "
    "stock, no at the market program or shelf capacity, and no share "
    "count growth."
)


def financing_field_metrics(
    supporting_passage_key: str,
) -> tuple[NormalizedMetricFact, ...]:
    definitions = (
        ("options", "option_shares_outstanding", "shares"),
        ("warrants", "warrant_shares_outstanding", "shares"),
        (
            "convertibles",
            "convertible_share_equivalents",
            "shares",
        ),
        ("rsus", "rsu_shares_outstanding", "shares"),
        ("preferreds", "preferred_shares_outstanding", "shares"),
        ("atm_shelf_capacity", "atm_capacity", "USD"),
        ("share_growth", "share_count_growth", "percent"),
    )
    return tuple(
        NormalizedMetricFact(
            reference_key=f"financing-metric:{field_id}",
            source_class="financing",
            metric_key=metric_key,
            value="0",
            unit=unit,
            period_start=None,
            period_end=date(2026, 3, 31),
            calculation_method="reported",
            formula=None,
            supporting_passage_keys=(supporting_passage_key,),
        )
        for field_id, metric_key, unit in definitions
    )


def request() -> PrimarySourceRequest:
    return PrimarySourceRequest(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik="0001601830",
        issuer_name="Example Therapeutics, Inc.",
        primary_listing_exchange="NASDAQ",
        as_of_cutoff=CUTOFF,
    )


def verified_sec_chain(
    issuer_name: str = "Recursion Pharmaceuticals, Inc.",
):
    source_request = request()
    submissions = collected_snapshot(
        fixture="rxrx-submissions.json",
        security_id=SECURITY_ID,
        cik="0001601830",
        issuer_name=issuer_name,
    )
    source_request = replace(
        source_request,
        issuer_name=issuer_name,
    )
    selection = RequiredSecFilingSelector().select(submissions)
    documents = tuple(
        SecFilingDocument(
            operator_id=source_request.operator_id,
            security_id=source_request.security_id,
            cik=source_request.cik,
            accession_number=filing.accession_number,
            form=filing.form,
            filing_date=filing.filing_date,
            report_date=filing.report_date,
            primary_document=filing.primary_document,
            source_class="sec_filing",
            source_url=filing.archive_url,
            published_at=filing.published_at,
            publication_date=filing.publication_date,
            retrieved_at=datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
            content_sha256=hashlib.sha256(
                (
                    f"<html><body>{SEC_PASSAGE}</body></html>"
                    if filing.accession_number == "0001601830-26-000040"
                    else "<html><body>selected filing</body></html>"
                ).encode()
            ).hexdigest(),
            content_text=(
                f"<html><body>{SEC_PASSAGE}</body></html>"
                if filing.accession_number == "0001601830-26-000040"
                else "<html><body>selected filing</body></html>"
            ),
        )
        for filing in selection.selected_filings
    )
    document_snapshot = SecFilingDocumentSnapshot(
        operator_id=source_request.operator_id,
        security_id=source_request.security_id,
        cik=source_request.cik,
        as_of_cutoff=source_request.as_of_cutoff,
        policy_version=selection.policy_version,
        documents=documents,
    )
    exhibit_snapshot = SecFilingExhibitSnapshot(
        operator_id=source_request.operator_id,
        security_id=source_request.security_id,
        cik=source_request.cik,
        as_of_cutoff=source_request.as_of_cutoff,
        policy_version="sec-html-exhibits-v1",
        indexes=(),
        references=(),
        exhibits=(),
    )
    exact = SecExactPassageExtractor().extract(
        next(
            document
            for document in documents
            if document.accession_number == "0001601830-26-000040"
        ),
        SEC_PASSAGE,
    )
    return (
        source_request,
        submissions,
        selection,
        document_snapshot,
        exhibit_snapshot,
        exact,
    )


class FixtureTransport:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def request(self, url: str, *, headers):
        del headers
        return OfficialBytesResponse(
            body=self.body,
            status=200,
            headers={"Content-Type": "text/html"},
            final_url=url,
        )


class PrimarySourceAdapterTests(unittest.TestCase):
    def test_official_snapshot_maps_exact_passages_and_coverage(self) -> None:
        body = Path(
            "tests/fixtures/official_sources/issuer-programme-update.html"
        ).read_bytes()
        snapshot = OfficialIssuerEvidenceAdapter(
            allowed_hosts=("investors.example-biotech.com",),
            transport=FixtureTransport(body),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        ).collect(
            request(),
            (
                OfficialSourceLocator(
                    source_key="programme-update-2026-q1",
                    requirement_id="issuer_pipeline",
                    title="Programme update",
                    source_url=ISSUER_URL,
                    publication_time="2026-05-05T20:00:00Z",
                    effective_date=date(2026, 5, 5),
                    passages=(
                        OfficialPassageSpec(
                            passage_key="phase-2-timing",
                            locator="main > p",
                            exact_text=ISSUER_PASSAGE,
                        ),
                    ),
                ),
            ),
        )

        passages = official_snapshot_pipeline_inputs(snapshot)
        proofs = official_snapshot_coverage_proofs(snapshot)

        self.assertEqual(len(passages), 1)
        self.assertEqual(passages[0].source_class, "issuer")
        self.assertEqual(
            passages[0].coverage_keys,
            frozenset({"issuer_pipeline"}),
        )
        self.assertEqual(passages[0].passage_text, ISSUER_PASSAGE)
        self.assertEqual(passages[0].canonical_url, ISSUER_URL)
        self.assertEqual(
            passages[0].effective_at,
            datetime(2026, 5, 5, 0, 0, tzinfo=UTC),
        )
        self.assertEqual(len(proofs), 1)
        self.assertEqual(proofs[0].requirement_id, "issuer_pipeline")
        self.assertEqual(
            proofs[0].policy_version,
            "official-issuer-source-v1",
        )
        self.assertEqual(
            proofs[0].evidence_reference_keys,
            (passages[0].reference_key,),
        )

    def test_regulatory_coverage_requires_programme_designation_bridge(self) -> None:
        body = (
            b'<p>"name":"REC-4881"</p>'
            b'<p>"codeSystem":"FDA ORPHAN DRUG","code":"817621"</p>'
        )
        snapshot = FDARegulatoryEvidenceAdapter(
            allowed_hosts=("precision.fda.gov",),
            transport=FixtureTransport(body),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        ).collect(
            request(),
            (
                OfficialSourceLocator(
                    source_key="fda-rec-4881-bridge",
                    requirement_id="us_regulatory",
                    title="REC-4881 FDA bridge",
                    source_url="https://precision.fda.gov/rec-4881",
                    publication_time="2026-05-05T20:00:00Z",
                    effective_date=date(2026, 5, 5),
                    passages=(
                        OfficialPassageSpec(
                            passage_key="programme-name",
                            locator="$.names",
                            exact_text='"name":"REC-4881"',
                        ),
                        OfficialPassageSpec(
                            passage_key="orphan-designation",
                            locator="$.codes",
                            exact_text=(
                                '"codeSystem":"FDA ORPHAN DRUG","code":"817621"'
                            ),
                        ),
                    ),
                ),
            ),
        )

        passages = official_snapshot_pipeline_inputs(
            snapshot,
            regulatory_program_names=("REC-4881",),
        )
        proofs = official_snapshot_coverage_proofs(
            snapshot,
            regulatory_program_names=("REC-4881",),
        )

        self.assertTrue(
            any("us_regulatory" in passage.coverage_keys for passage in passages)
        )
        self.assertEqual(proofs[0].state, "complete")
        self.assertEqual(proofs[0].policy_version, "fda-regulatory-source-v2")

    def test_regulatory_coverage_rejects_sponsor_only_designation(self) -> None:
        body = (
            b"<p>Designation Date 10/10/2023</p>"
            b"<p>Sponsor SELLAS Life Sciences Group, Inc.</p>"
        )
        snapshot = FDARegulatoryEvidenceAdapter(
            allowed_hosts=("www.accessdata.fda.gov",),
            transport=FixtureTransport(body),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        ).collect(
            request(),
            (
                OfficialSourceLocator(
                    source_key="fda-oopd-965323",
                    requirement_id="us_regulatory",
                    title="SLS orphan designation",
                    source_url=(
                        "https://www.accessdata.fda.gov/scripts/opdlisting/"
                        "oopd/detailedIndex.cfm?cfgridkey=965323"
                    ),
                    publication_time="2023-10-10",
                    effective_date=date(2023, 10, 10),
                    passages=(
                        OfficialPassageSpec(
                            passage_key="designation-date",
                            locator="Designation Date",
                            exact_text="Designation Date 10/10/2023",
                        ),
                        OfficialPassageSpec(
                            passage_key="sponsor",
                            locator="Sponsor",
                            exact_text="Sponsor SELLAS Life Sciences Group, Inc.",
                        ),
                    ),
                ),
            ),
        )

        passages = official_snapshot_pipeline_inputs(
            snapshot,
            regulatory_program_names=("SLS009", "tambiciclib"),
        )
        proofs = official_snapshot_coverage_proofs(
            snapshot,
            regulatory_program_names=("SLS009", "tambiciclib"),
        )

        self.assertTrue(all(not passage.coverage_keys for passage in passages))
        self.assertEqual(proofs[0].state, "incomplete")
        self.assertEqual(
            proofs[0].reason_codes,
            ("regulatory_programme_linkage_unresolved",),
        )

    def test_regulatory_proof_references_only_linked_source_passages(self) -> None:
        body = (
            b'<p>"name":"REC-4881"</p>'
            b'<p>"codeSystem":"FDA ORPHAN DRUG","code":"817621"</p>'
            b"<p>Treatment of familial adenomatous polyposis</p>"
        )
        snapshot = FDARegulatoryEvidenceAdapter(
            allowed_hosts=("precision.fda.gov",),
            transport=FixtureTransport(body),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        ).collect(
            request(),
            (
                OfficialSourceLocator(
                    source_key="fda-rec-4881-bridge",
                    requirement_id="us_regulatory",
                    title="REC-4881 FDA bridge",
                    source_url="https://precision.fda.gov/rec-4881",
                    publication_time="2026-05-05T20:00:00Z",
                    effective_date=date(2026, 5, 5),
                    passages=(
                        OfficialPassageSpec(
                            passage_key="programme-name",
                            locator="$.names",
                            exact_text='"name":"REC-4881"',
                        ),
                        OfficialPassageSpec(
                            passage_key="orphan-designation",
                            locator="$.codes",
                            exact_text=(
                                '"codeSystem":"FDA ORPHAN DRUG","code":"817621"'
                            ),
                        ),
                    ),
                ),
                OfficialSourceLocator(
                    source_key="fda-oopd-817621",
                    requirement_id="us_regulatory",
                    title="FDA orphan designation record",
                    source_url="https://precision.fda.gov/oopd-817621",
                    publication_time="2021-09-28",
                    effective_date=date(2021, 9, 28),
                    passages=(
                        OfficialPassageSpec(
                            passage_key="orphan-indication",
                            locator="Indication",
                            exact_text=("Treatment of familial adenomatous polyposis"),
                        ),
                    ),
                ),
            ),
        )

        passages = official_snapshot_pipeline_inputs(
            snapshot,
            regulatory_program_names=("REC-4881",),
        )
        proof = official_snapshot_coverage_proofs(
            snapshot,
            regulatory_program_names=("REC-4881",),
        )[0]

        linked_references = tuple(
            passage.reference_key
            for passage in passages
            if "us_regulatory" in passage.coverage_keys
        )
        self.assertEqual(proof.state, "complete")
        self.assertEqual(proof.evidence_reference_keys, linked_references)
        self.assertNotIn(
            "regulatory:fda-oopd-817621:orphan-indication",
            proof.evidence_reference_keys,
        )

    def test_sec_exact_passage_maps_to_sec_primary_evidence(self) -> None:
        (
            source_request,
            submissions,
            selection,
            documents,
            exhibits,
            exact,
        ) = verified_sec_chain()

        passage = sec_passage_pipeline_input(
            source_request,
            exact,
            reference_key="sec-clinical-update",
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
        )

        proofs = sec_snapshot_coverage_proofs(
            source_request,
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
            passages=(passage,),
        )

        self.assertEqual(passage.source_class, "sec")
        self.assertEqual(passage.passage_text, SEC_PASSAGE)
        self.assertEqual(
            passage.document_content_hash,
            exact.source_content_sha256,
        )
        self.assertEqual(
            passage.coverage_keys,
            frozenset({"sec_issuer_security", "required_sec_filings"}),
        )
        self.assertEqual(
            {proof.requirement_id: proof.state for proof in proofs},
            {
                "required_sec_filings": "complete",
                "sec_issuer_security": "complete",
            },
        )

    def test_sec_coverage_proof_rejects_forged_passage_provenance(
        self,
    ) -> None:
        (
            source_request,
            submissions,
            selection,
            documents,
            exhibits,
            exact,
        ) = verified_sec_chain()
        passage = sec_passage_pipeline_input(
            source_request,
            exact,
            reference_key="sec-clinical-update",
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
        )
        forged = replace(
            passage,
            canonical_url=(
                "https://www.sec.gov/Archives/edgar/data/1601830/"
                "000160183026000040/forged.htm"
            ),
        )

        with self.assertRaisesRegex(
            PrimarySourcePipelineError,
            "provenance",
        ):
            sec_snapshot_coverage_proofs(
                source_request,
                submissions=submissions,
                selection=selection,
                documents=documents,
                exhibits=exhibits,
                passages=(forged,),
            )

    def test_sec_identity_mismatch_cannot_create_identity_proof(
        self,
    ) -> None:
        (
            source_request,
            submissions,
            selection,
            documents,
            exhibits,
            exact,
        ) = verified_sec_chain("Unrelated Biotech, Inc.")

        passage = sec_passage_pipeline_input(
            source_request,
            exact,
            reference_key="sec-clinical-update",
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
        )
        proofs = sec_snapshot_coverage_proofs(
            source_request,
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
            passages=(passage,),
        )

        identity = next(
            proof for proof in proofs if proof.requirement_id == "sec_issuer_security"
        )
        self.assertNotIn(
            "sec_issuer_security",
            passage.coverage_keys,
        )
        self.assertEqual(identity.state, "incomplete")
        self.assertEqual(
            identity.reason_codes,
            ("sec_issuer_name_not_in_verified_history",),
        )
        self.assertEqual(identity.evidence_reference_keys, ())

    def test_material_unsupported_exhibit_blocks_required_filing_coverage(
        self,
    ) -> None:
        (
            source_request,
            submissions,
            selection,
            documents,
            exhibits,
            exact,
        ) = verified_sec_chain()
        unsupported = SecFilingExhibitReference(
            accession_number=exact.accession_number,
            sequence="2",
            description="Material agreement",
            exhibit_type="EX-10.1",
            document_name="agreement.pdf",
            source_class="sec_filing_exhibit",
            source_url=(
                "https://www.sec.gov/Archives/edgar/data/1601830/"
                "000160183026000040/agreement.pdf"
            ),
            collection_state="unsupported_media",
        )
        exhibits = replace(exhibits, references=(unsupported,))

        passage = sec_passage_pipeline_input(
            source_request,
            exact,
            reference_key="sec-clinical-update",
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
        )
        proofs = sec_snapshot_coverage_proofs(
            source_request,
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
            passages=(passage,),
        )

        self.assertEqual(
            passage.coverage_keys,
            frozenset({"sec_issuer_security"}),
        )
        required = next(
            proof for proof in proofs if proof.requirement_id == "required_sec_filings"
        )
        self.assertEqual(required.state, "indeterminate")
        self.assertEqual(
            required.reason_codes,
            ("sec_material_exhibit_unsupported_media",),
        )

    def test_companyfacts_and_empty_scan_still_need_capital_passage(
        self,
    ) -> None:
        (
            source_request,
            submissions,
            selection,
            documents,
            exhibits,
            _exact,
        ) = verified_sec_chain()
        payload = json.loads(COMPANYFACTS_FIXTURE.read_text())
        payload["entityName"] = source_request.issuer_name
        companyfacts = SecCompanyFactsCollector(
            SecCompanyFactsSettings(
                user_agent="Investment Research OS research@example.com"
            ),
            transport=CompanyFactsTransport(json.dumps(payload).encode()),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        ).collect(source_request)
        core_passages, metrics = companyfacts_pipeline_inputs(companyfacts)

        passages, proof, semantic_facts = sec_financing_coverage_inputs(
            source_request,
            companyfacts=companyfacts,
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
            core_passages=core_passages,
            core_metrics=metrics,
        )

        self.assertEqual(proof.state, "incomplete")
        self.assertEqual(semantic_facts, ())
        self.assertEqual(
            proof.policy_version,
            "biotech-financing-share-capital-v1",
        )
        self.assertIn(
            "sec_capital_structure_passage_missing",
            proof.reason_codes,
        )
        self.assertTrue(all(not passage.coverage_keys for passage in passages))
        self.assertEqual(
            proof.evidence_reference_keys,
            tuple(passage.reference_key for passage in passages),
        )

    def test_selected_financing_filing_requires_verified_passage(
        self,
    ) -> None:
        (
            source_request,
            submissions,
            selection,
            documents,
            exhibits,
            _exact,
        ) = verified_sec_chain()
        requirements = tuple(
            replace(
                result,
                selected_accessions=("0001601830-26-000040",),
            )
            if result.requirement_id == "sec_financing_filing_scan"
            else result
            for result in selection.requirement_results
        )
        selection = replace(
            selection,
            requirement_results=requirements,
        )
        payload = json.loads(COMPANYFACTS_FIXTURE.read_text())
        payload["entityName"] = source_request.issuer_name
        companyfacts = SecCompanyFactsCollector(
            SecCompanyFactsSettings(
                user_agent="Investment Research OS research@example.com"
            ),
            transport=CompanyFactsTransport(json.dumps(payload).encode()),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        ).collect(source_request)
        core_passages, metrics = companyfacts_pipeline_inputs(companyfacts)

        passages, proof, semantic_facts = sec_financing_coverage_inputs(
            source_request,
            companyfacts=companyfacts,
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
            core_passages=core_passages,
            core_metrics=metrics,
        )

        self.assertEqual(proof.state, "incomplete")
        self.assertEqual(semantic_facts, ())
        self.assertIn(
            "sec_financing_filing_passage_missing",
            proof.reason_codes,
        )
        self.assertTrue(all(not passage.coverage_keys for passage in passages))

    def test_verified_financing_passage_completes_selected_scan(
        self,
    ) -> None:
        (
            source_request,
            submissions,
            selection,
            documents,
            exhibits,
            exact,
        ) = verified_sec_chain()
        selection = replace(
            selection,
            requirement_results=tuple(
                replace(
                    result,
                    selected_accessions=(exact.accession_number,),
                )
                if result.requirement_id == "sec_financing_filing_scan"
                else result
                for result in selection.requirement_results
            ),
        )
        quarterly = next(
            document
            for document in documents.documents
            if document.accession_number == exact.accession_number
        )
        quarterly = replace(
            quarterly,
            content_text=(f"<html><body>{FINANCING_SEMANTIC_PASSAGE}</body></html>"),
            content_sha256=hashlib.sha256(
                (f"<html><body>{FINANCING_SEMANTIC_PASSAGE}</body></html>").encode()
            ).hexdigest(),
        )
        documents = replace(
            documents,
            documents=tuple(
                quarterly
                if document.accession_number == quarterly.accession_number
                else document
                for document in documents.documents
            ),
        )
        exact = SecExactPassageExtractor().extract(
            quarterly,
            FINANCING_SEMANTIC_PASSAGE,
        )
        filing_passage = sec_financing_passage_pipeline_input(
            source_request,
            exact,
            reference_key="financing:quarterly-disclosure",
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
        )
        payload = json.loads(COMPANYFACTS_FIXTURE.read_text())
        payload["entityName"] = source_request.issuer_name
        companyfacts = SecCompanyFactsCollector(
            SecCompanyFactsSettings(
                user_agent="Investment Research OS research@example.com"
            ),
            transport=CompanyFactsTransport(json.dumps(payload).encode()),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        ).collect(source_request)
        core_passages, metrics = companyfacts_pipeline_inputs(companyfacts)

        filing_metrics = financing_field_metrics(filing_passage.reference_key)
        passages, proof, semantic_facts = sec_financing_coverage_inputs(
            source_request,
            companyfacts=companyfacts,
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
            core_passages=core_passages,
            core_metrics=metrics,
            filing_passages=(filing_passage,),
            filing_metrics=filing_metrics,
            field_evidence=tuple(
                FinancingFieldEvidence(
                    field_id=field_id,
                    outcome=("complete" if field_id == "basic_shares" else "absent"),
                    evidence_reference_keys=(
                        "sec-companyfacts:basic_shares_outstanding"
                        if field_id == "basic_shares"
                        else f"financing-metric:{field_id}",
                    ),
                )
                for field_id in FINANCING_FIELD_IDS
            ),
        )

        self.assertEqual(filing_passage.source_class, "financing")
        self.assertEqual(filing_passage.coverage_keys, frozenset())
        self.assertEqual(proof.state, "complete", proof.reason_codes)
        self.assertEqual(len(semantic_facts), 8)
        self.assertTrue(
            all(fact.metric_reference_key is not None for fact in semantic_facts)
        )
        self.assertTrue(
            all(
                passage.coverage_keys == frozenset({"financing_share_capital"})
                for passage in passages
            )
        )

    def test_capital_passage_without_semantic_matrix_stays_incomplete(
        self,
    ) -> None:
        (
            source_request,
            submissions,
            selection,
            documents,
            exhibits,
            exact,
        ) = verified_sec_chain()
        selection = replace(
            selection,
            requirement_results=tuple(
                replace(
                    result,
                    selected_accessions=(exact.accession_number,),
                )
                if result.requirement_id == "sec_financing_filing_scan"
                else result
                for result in selection.requirement_results
            ),
        )
        filing_passage = sec_financing_passage_pipeline_input(
            source_request,
            exact,
            reference_key="financing:capital-structure",
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
        )
        payload = json.loads(COMPANYFACTS_FIXTURE.read_text())
        payload["entityName"] = source_request.issuer_name
        companyfacts = SecCompanyFactsCollector(
            SecCompanyFactsSettings(
                user_agent="Investment Research OS research@example.com"
            ),
            transport=CompanyFactsTransport(json.dumps(payload).encode()),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        ).collect(source_request)
        core_passages, metrics = companyfacts_pipeline_inputs(companyfacts)

        passages, proof, semantic_facts = sec_financing_coverage_inputs(
            source_request,
            companyfacts=companyfacts,
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
            core_passages=core_passages,
            core_metrics=metrics,
            filing_passages=(filing_passage,),
        )

        self.assertEqual(proof.state, "incomplete")
        self.assertEqual(semantic_facts, ())
        self.assertIn(
            "financing_semantic_matrix_missing",
            proof.reason_codes,
        )
        self.assertIn(
            "financing_field_warrants_unresolved",
            proof.reason_codes,
        )
        self.assertTrue(all(not passage.coverage_keys for passage in passages))


if __name__ == "__main__":
    unittest.main()
