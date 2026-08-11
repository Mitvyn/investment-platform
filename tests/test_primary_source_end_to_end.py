from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import unittest
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, uuid5
from zipfile import ZIP_STORED, ZipFile

from investment_research_os.evidence_bundles import (
    EvidenceBundleWorkflow,
    InMemoryEvidenceBundleRepository,
)
from investment_research_os.research_runs import (
    AuthenticatedOperator,
    InMemoryResearchRunRepository,
    QUESTION_TYPE,
    ResearchRunWorkflow,
    WORKFLOW_CONFIG_VERSION,
)
from workers.clinical_trials.collector import (
    ClinicalTrialsCollector,
    ClinicalTrialsSettings,
    clinical_trials_coverage_proof,
    clinical_trials_pipeline_inputs,
)
from workers.official_sources import (
    OfficialIssuerEvidenceAdapter,
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
from workers.primary_sources.captures import (
    CAPTURE_CONTRACT_VERSION,
    load_primary_source_capture,
)
from workers.primary_sources.acquisition import (
    acquire_primary_source_capture,
)
from workers.primary_sources.financing import (
    FINANCING_FIELD_IDS,
    FinancingFieldEvidence,
)
from workers.primary_sources.eligibility import (
    derive_biotech_eligibility_profile,
)
from workers.primary_sources.models import PrimarySourceRequest
from workers.primary_sources.plans import (
    InMemoryPrimarySourcePlanRepository,
    PRIMARY_SOURCE_PLAN_VERSION,
    PrimarySourcePlanError,
    bind_primary_source_plan,
    load_primary_source_plan,
    resolve_sec_passage_sources,
)
from workers.primary_sources.pipeline import (
    NormalizedCatalystFact,
    NormalizedMetricFact,
    NormalizedRiskFact,
    PrimarySourcePipeline,
)
from workers.regulatory import FDARegulatoryEvidenceAdapter
from workers.sec.collector import BytesResponse, SecSettings
from workers.sec.documents import SecFilingDocumentCollector
from workers.sec.exhibits import SecFilingExhibitCollector
from workers.sec.passages import SecExactPassageExtractor
from workers.sec.selection import RequiredSecFilingSelector
from workers.sec.submissions import SecSubmissionsCollector
from workers.security_registry.client import SecurityRegistryClient
from tests.test_official_sources import (
    FDA_PASSAGE,
    FDA_URL,
    ISSUER_URL,
    PASSAGE as ISSUER_PASSAGE,
)
from tests.test_sec_passages import PASSAGE as SEC_PASSAGE


OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
SECURITY_ID = "a657d245-6bda-5476-930a-911667ea6c64"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)
CREATED_AT = datetime(2026, 5, 7, 1, 30, tzinfo=UTC)
CAPITAL_PASSAGE = (
    "The company reported basic shares, no stock options, no warrants, "
    "no convertible securities, no restricted stock units, no preferred "
    "stock, no at the market program or shelf capacity, and no share "
    "count growth."
)
COMMON_EQUITY_PASSAGE = "Our common stock is listed on the Nasdaq Global Select Market."


@dataclass(frozen=True, slots=True)
class IntegratedFixtureCase:
    security_id: str
    cik: str
    issuer_name: str
    display_symbol: str
    submissions_fixture: str
    companyfacts_fixture: str
    issuer_fixture: str
    issuer_url: str
    issuer_trusted_hosts: tuple[str, ...]
    issuer_source_key: str
    issuer_passage_key: str
    issuer_passage: str
    clinical_fixture: str
    clinical_program: str
    clinical_terms: tuple[str, ...]
    clinical_nct_id: str
    regulatory_fixture: str
    regulatory_url: str
    regulatory_source_key: str
    regulatory_passage_key: str
    regulatory_passage: str
    sec_passage: str
    identity_listing_form: str
    catalyst_reference_key: str
    catalyst_event: str
    catalyst_window_start: date
    catalyst_window_end: date
    expected_cash: str
    expected_operating_cash_used: str
    expected_clinical_passages: int


PLATFORM_CASE = IntegratedFixtureCase(
    security_id=SECURITY_ID,
    cik="0001601830",
    issuer_name="Example Therapeutics, Inc.",
    display_symbol="EXMP",
    submissions_fixture="generic-submissions.json",
    companyfacts_fixture="sec-companyfacts.json",
    issuer_fixture="issuer-programme-update.html",
    issuer_url=ISSUER_URL,
    issuer_trusted_hosts=("investors.example-biotech.com",),
    issuer_source_key="programme-update",
    issuer_passage_key="catalyst-window",
    issuer_passage=ISSUER_PASSAGE,
    clinical_fixture="clinical-trials-programme.json",
    clinical_program="Example oncology programme",
    clinical_terms=("Asset Alpha", "Asset Beta"),
    clinical_nct_id="NCT06000001",
    regulatory_fixture="fda-regulatory-update.html",
    regulatory_url=FDA_URL,
    regulatory_source_key="fast-track-update",
    regulatory_passage_key="fast-track-designation",
    regulatory_passage=FDA_PASSAGE,
    sec_passage=SEC_PASSAGE,
    identity_listing_form="10-Q",
    catalyst_reference_key="example-phase-2-topline",
    catalyst_event="Example Phase 2 top-line data",
    catalyst_window_start=date(2026, 10, 1),
    catalyst_window_end=date(2026, 12, 31),
    expected_cash="474300000",
    expected_operating_cash_used="118700000",
    expected_clinical_passages=2,
)

SINGLE_ASSET_CASE = IntegratedFixtureCase(
    security_id="4c86acc7-96b2-5f8b-966d-b7d57b832069",
    cik="0001900001",
    issuer_name="Single Asset Therapeutics, Inc.",
    display_symbol="SNGA",
    submissions_fixture="single-asset-e2e-submissions.json",
    companyfacts_fixture="single-asset-e2e-companyfacts.json",
    issuer_fixture="single-asset-issuer-update.html",
    issuer_url=("https://investors.single-asset.example/news/pivotal-update.html"),
    issuer_trusted_hosts=("investors.single-asset.example",),
    issuer_source_key="pivotal-update",
    issuer_passage_key="phase-3-timing",
    issuer_passage=(
        "The single pivotal Phase 3 programme remains on track for "
        "top-line data in the third quarter of 2026."
    ),
    clinical_fixture="single-asset-clinical-trial.json",
    clinical_program="Lead-901 pivotal programme",
    clinical_terms=("Lead-901",),
    clinical_nct_id="NCT07000001",
    regulatory_fixture="single-asset-fda-update.html",
    regulatory_url=(
        "https://www.fda.gov/drugs/news-events/lead-901-breakthrough-therapy"
    ),
    regulatory_source_key="breakthrough-therapy-update",
    regulatory_passage_key="breakthrough-therapy-designation",
    regulatory_passage=("FDA granted Breakthrough Therapy designation for Lead-901."),
    sec_passage=(
        "The pivotal Phase 3 study completed enrollment and remains "
        "on track for top-line data."
    ),
    identity_listing_form="10-K",
    catalyst_reference_key="lead-901-phase-3-topline",
    catalyst_event="Lead-901 Phase 3 top-line data",
    catalyst_window_start=date(2026, 7, 1),
    catalyst_window_end=date(2026, 9, 30),
    expected_cash="85000000",
    expected_operating_cash_used="45000000",
    expected_clinical_passages=1,
)


def request(case: IntegratedFixtureCase) -> PrimarySourceRequest:
    return PrimarySourceRequest(
        operator_id=OPERATOR_ID,
        security_id=case.security_id,
        cik=case.cik,
        issuer_name=case.issuer_name,
        primary_listing_exchange="NASDAQ",
        as_of_cutoff=CUTOFF,
    )


def source_plan_value(case: IntegratedFixtureCase) -> dict[str, object]:
    return {
        "contract_version": PRIMARY_SOURCE_PLAN_VERSION,
        "plan_id": str(
            uuid5(
                NAMESPACE_URL,
                f"primary-source-plan:{case.security_id}",
            )
        ),
        "revision": 1,
        "effective_at": "2026-05-04T00:00:00Z",
        "question_type": QUESTION_TYPE,
        "workflow_config_version": WORKFLOW_CONFIG_VERSION,
        "security": {
            "security_id": case.security_id,
            "cik": case.cik,
            "issuer_name": case.issuer_name,
            "primary_listing_exchange": "NASDAQ",
        },
        "sec_passages": [
            {
                "reference_key": "sec-required-filings",
                "role": "required_filing",
                "selected_form": "10-Q",
                "exact_text": case.sec_passage,
            },
            {
                "reference_key": "sec-identity-and-listing",
                "role": "identity_listing",
                "selected_form": case.identity_listing_form,
                "exact_text": COMMON_EQUITY_PASSAGE,
            },
            {
                "reference_key": "financing:capital-structure",
                "role": "financing",
                "selected_form": "10-Q",
                "exact_text": CAPITAL_PASSAGE,
            },
        ],
        "issuer_sources": [
            {
                "source_key": case.issuer_source_key,
                "requirement_id": "issuer_pipeline",
                "title": "Programme update",
                "source_url": case.issuer_url,
                "publication_time": "2026-05-05T20:00:00Z",
                "effective_date": "2026-05-05",
                "coverage_role": "required",
                "coverage_mode": "all",
                "passages": [
                    {
                        "passage_key": case.issuer_passage_key,
                        "locator": "main > p",
                        "exact_text": case.issuer_passage,
                    }
                ],
            }
        ],
        "clinical_trial_search": {
            "program_name": case.clinical_program,
            "search_terms": list(case.clinical_terms),
            "allowed_sponsor_names": [],
        },
        "regulatory_sources": [
            {
                "source_key": case.regulatory_source_key,
                "requirement_id": "us_regulatory",
                "title": "FDA regulatory update",
                "source_url": case.regulatory_url,
                "publication_time": "2026-05-04T18:00:00Z",
                "effective_date": "2026-05-04",
                "coverage_role": "required",
                "coverage_mode": "all",
                "passages": [
                    {
                        "passage_key": case.regulatory_passage_key,
                        "locator": "main > p",
                        "exact_text": case.regulatory_passage,
                    }
                ],
            }
        ],
    }


def clinical_trials_url(search_terms: tuple[str, ...]) -> str:
    query = " OR ".join(f'"{term}"' for term in search_terms)
    return "https://clinicaltrials.gov/api/v2/studies?" + urlencode(
        {
            "format": "json",
            "pageSize": 100,
            "countTotal": "true",
            "query.term": query,
        }
    )


def capture_archive(
    case: IntegratedFixtureCase,
    *,
    source_plan_bytes: bytes,
    source_plan,
    registry_body: bytes,
    submissions_body: bytes,
    selected_filings,
    document_bodies: dict[str, bytes],
    index_bodies: dict[str, bytes],
    issuer_body: bytes,
    trial_body: bytes,
    regulatory_body: bytes,
    companyfacts_body: bytes,
) -> bytes:
    payloads: dict[str, bytes] = {}
    responses: list[dict[str, object]] = []

    def add_response(
        response_key: str,
        route: dict[str, object],
        request_url: str,
        body: bytes,
        media_type: str,
    ) -> None:
        body_sha256 = hashlib.sha256(body).hexdigest()
        body_path = f"payloads/{body_sha256}.bin"
        payloads[body_path] = body
        responses.append(
            {
                "response_key": response_key,
                "route": route,
                "request_url": request_url,
                "final_url": request_url,
                "status": 200,
                "headers": {"content-type": media_type},
                "retrieved_at": CREATED_AT.isoformat(),
                "body": {
                    "path": body_path,
                    "byte_length": len(body),
                    "sha256": body_sha256,
                },
            }
        )

    add_response(
        "security-registry",
        {"role": "sec_security_registry"},
        "https://www.sec.gov/files/company_tickers_exchange.json",
        registry_body,
        "application/json",
    )
    add_response(
        "submissions-root",
        {"role": "sec_submissions_root"},
        f"https://data.sec.gov/submissions/CIK{case.cik}.json",
        submissions_body,
        "application/json",
    )
    add_response(
        "companyfacts",
        {"role": "sec_companyfacts"},
        (f"https://data.sec.gov/api/xbrl/companyfacts/CIK{case.cik}.json"),
        companyfacts_body,
        "application/json",
    )
    for ordinal, filing in enumerate(selected_filings):
        add_response(
            f"filing-document-{ordinal}",
            {
                "role": "sec_filing_document",
                "accession_number": filing.accession_number,
                "primary_document": filing.primary_document,
            },
            filing.archive_url,
            document_bodies[filing.archive_url],
            "text/html",
        )
        index_url = (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{case.cik.lstrip('0') or '0'}/"
            f"{filing.accession_number.replace('-', '')}/"
            f"{filing.accession_number}-index.html"
        )
        add_response(
            f"filing-index-{ordinal}",
            {
                "role": "sec_filing_index",
                "accession_number": filing.accession_number,
            },
            index_url,
            index_bodies[index_url],
            "text/html",
        )
    add_response(
        "issuer-document",
        {
            "role": "issuer_document",
            "source_key": case.issuer_source_key,
        },
        case.issuer_url,
        issuer_body,
        "text/html",
    )
    add_response(
        "clinical-trials-page-0",
        {
            "role": "clinical_trials_page",
            "page_ordinal": 0,
        },
        clinical_trials_url(case.clinical_terms),
        trial_body,
        "application/json",
    )
    add_response(
        "regulatory-document",
        {
            "role": "regulatory_document",
            "source_key": case.regulatory_source_key,
        },
        case.regulatory_url,
        regulatory_body,
        "text/html",
    )
    manifest = {
        "contract_version": CAPTURE_CONTRACT_VERSION,
        "capture_id": str(
            uuid5(
                NAMESPACE_URL,
                f"primary-source-capture:{case.security_id}",
            )
        ),
        "revision": 1,
        "provenance_mode": "operator_supplied_unverified",
        "assembled_at": datetime(2026, 5, 7, 2, tzinfo=UTC).isoformat(),
        "context": {
            "operator_id": OPERATOR_ID,
            "security_id": case.security_id,
            "cik": case.cik,
            "issuer_name": case.issuer_name,
            "primary_listing_exchange": "NASDAQ",
            "as_of_cutoff": CUTOFF.isoformat(),
            "question_type": QUESTION_TYPE,
            "workflow_config_version": WORKFLOW_CONFIG_VERSION,
        },
        "plan": {
            "path": "primary-source-plan.json",
            "plan_id": source_plan.loaded.plan_id,
            "revision": source_plan.loaded.revision,
            "content_hash": source_plan.content_hash,
        },
        "responses": responses,
    }
    entries = {
        "capture.json": json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
        "primary-source-plan.json": source_plan_bytes,
        **payloads,
    }
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        for name, body in sorted(entries.items()):
            archive.writestr(name, body)
    return output.getvalue()


def financing_field_metrics(
    supporting_passage_key: str,
    period_end: date,
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
            period_end=period_end,
            calculation_method="reported",
            formula=None,
            supporting_passage_keys=(supporting_passage_key,),
        )
        for field_id, metric_key, unit in definitions
    )


class SecTransport:
    def __init__(self, body: bytes, url: str) -> None:
        self.body = body
        self.url = url

    def request(self, url: str, *, headers):
        del headers
        return BytesResponse(
            body=self.body,
            status=200,
            headers={"Content-Type": "application/json"},
            final_url=self.url,
        )


class FixedEligibilitySource:
    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot

    def load(self, operator_id: str, security_id: str, as_of_cutoff: datetime):
        del operator_id, security_id, as_of_cutoff
        return self.snapshot


class FixedEvidenceSource:
    def __init__(self, candidate) -> None:
        self.candidate = candidate

    def load(self, operator_id: str, security_id: str, as_of_cutoff: datetime):
        del operator_id, security_id, as_of_cutoff
        return self.candidate


class PrimarySourceEndToEndTests(unittest.TestCase):
    def _run_fixture(
        self,
        case: IntegratedFixtureCase,
    ):
        source_request = request(case)
        source_plan_bytes = json.dumps(
            source_plan_value(case),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        source_plan = bind_primary_source_plan(
            load_primary_source_plan(
                source_plan_bytes,
            ),
            source_request,
            trusted_issuer_hosts=case.issuer_trusted_hosts,
        )
        registry_body = json.dumps(
            {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [
                    [
                        int(case.cik),
                        case.issuer_name,
                        case.display_symbol,
                        "Nasdaq",
                    ]
                ],
            }
        ).encode()
        submissions_body = (
            Path("tests/fixtures/primary_sources")
            .joinpath(case.submissions_fixture)
            .read_bytes()
        )
        submissions_url = f"https://data.sec.gov/submissions/CIK{case.cik}.json"
        preflight_submissions = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS research@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=SecTransport(submissions_body, submissions_url),
            clock=lambda: CREATED_AT,
        ).discover(source_request)
        preflight_selection = RequiredSecFilingSelector().select(preflight_submissions)
        document_bodies: dict[str, bytes] = {}
        index_bodies: dict[str, bytes] = {}
        for filing in preflight_selection.selected_filings:
            planned_passages = tuple(
                plan.exact_text
                for plan in source_plan.sec_passages
                if plan.selected_form == filing.form
            )
            passage_html = "".join(f"<p>{passage}</p>" for passage in planned_passages)
            document_bodies[filing.archive_url] = (
                f"<html><body>{passage_html or 'selected filing'}</body></html>"
            ).encode()
            index_url = (
                "https://www.sec.gov/Archives/edgar/data/"
                f"{case.cik.lstrip('0') or '0'}/"
                f"{filing.accession_number.replace('-', '')}/"
                f"{filing.accession_number}-index.html"
            )
            index_bodies[index_url] = (
                "<html><body>"
                '<table summary="Document Format Files">'
                "<tr>"
                "<td>1</td><td>Primary filing</td>"
                f'<td><a href="{filing.primary_document}">'
                f"{filing.primary_document}</a></td>"
                f"<td>{filing.form}</td><td>1000</td>"
                "</tr></table></body></html>"
            ).encode()
        issuer_body = (
            Path("tests/fixtures/official_sources")
            .joinpath(case.issuer_fixture)
            .read_bytes()
        )
        trial_body = (
            Path("tests/fixtures/primary_sources")
            .joinpath(case.clinical_fixture)
            .read_bytes()
        )
        regulatory_body = (
            Path("tests/fixtures/official_sources")
            .joinpath(case.regulatory_fixture)
            .read_bytes()
        )
        companyfacts_body = (
            Path("tests/fixtures/primary_sources")
            .joinpath(case.companyfacts_fixture)
            .read_bytes()
        )
        response_bodies = {
            "https://www.sec.gov/files/company_tickers_exchange.json": (
                registry_body,
                "application/json",
            ),
            submissions_url: (submissions_body, "application/json"),
            (f"https://data.sec.gov/api/xbrl/companyfacts/CIK{case.cik}.json"): (
                companyfacts_body,
                "application/json",
            ),
            case.issuer_url: (issuer_body, "text/html"),
            clinical_trials_url(case.clinical_terms): (
                trial_body,
                "application/json",
            ),
            case.regulatory_url: (regulatory_body, "text/html"),
            **{
                url: (body, "text/html")
                for url, body in (
                    *document_bodies.items(),
                    *index_bodies.items(),
                )
            },
        }

        class CaptureTransport:
            def request(self, url: str, *, headers):
                del headers
                body, media_type = response_bodies[url]
                return BytesResponse(
                    body=body,
                    status=200,
                    headers={"Content-Type": media_type},
                    final_url=url,
                )

        capture = load_primary_source_capture(
            acquire_primary_source_capture(
                request=source_request,
                ticker=case.display_symbol,
                source_plan=source_plan_bytes,
                trusted_issuer_hosts=case.issuer_trusted_hosts,
                user_agent=("Investment Research OS research@example.com"),
                transport=CaptureTransport(),
                clock=lambda: CREATED_AT,
                capture_id=str(
                    uuid5(
                        NAMESPACE_URL,
                        f"primary-source-capture:{case.security_id}",
                    )
                ),
                revision=1,
                assembled_at=datetime(
                    2026,
                    5,
                    7,
                    2,
                    tzinfo=UTC,
                ),
            ).archive,
            request=source_request,
            trusted_issuer_hosts=case.issuer_trusted_hosts,
            accepted_at=lambda: datetime(2026, 5, 7, 3, tzinfo=UTC),
        )
        source_plan = capture.plan
        session = capture.open_session()
        plan_repository = InMemoryPrimarySourcePlanRepository()
        plan_repository.save(source_plan)
        sec_plans = {plan.role: plan for plan in source_plan.sec_passages}

        registry_transport = session.sec_transport()
        registry_security = SecurityRegistryClient(
            SecSettings(
                user_agent="Investment Research OS research@example.com",
                base_url="https://www.sec.gov",
            ),
            transport=registry_transport,
            clock=registry_transport.clock,
        ).resolve(case.display_symbol, operator_id=OPERATOR_ID)
        self.assertEqual(
            registry_security.security_id,
            source_request.security_id,
        )
        submissions_transport = session.sec_transport()
        submissions = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS research@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=submissions_transport,
            clock=submissions_transport.clock,
        ).discover(source_request)
        selection = RequiredSecFilingSelector().select(submissions)
        self.assertEqual(selection, preflight_selection)
        document_transport = session.sec_transport()
        documents = SecFilingDocumentCollector(
            SecSettings(user_agent="Investment Research OS research@example.com"),
            transport=document_transport,
            clock=document_transport.clock,
        ).collect(selection)
        exhibit_transport = session.sec_transport()
        exhibits = SecFilingExhibitCollector(
            SecSettings(user_agent="Investment Research OS research@example.com"),
            transport=exhibit_transport,
            clock=exhibit_transport.clock,
        ).collect(documents)
        resolved_sec_sources = {
            item.plan.role: item
            for item in resolve_sec_passage_sources(
                source_plan,
                documents,
            )
        }
        sec_passage = sec_passage_pipeline_input(
            source_request,
            SecExactPassageExtractor().extract(
                resolved_sec_sources["required_filing"].document,
                sec_plans["required_filing"].exact_text,
            ),
            reference_key=sec_plans["required_filing"].reference_key,
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
        )
        listing_passage = sec_passage_pipeline_input(
            source_request,
            SecExactPassageExtractor().extract(
                resolved_sec_sources["identity_listing"].document,
                sec_plans["identity_listing"].exact_text,
            ),
            reference_key=sec_plans["identity_listing"].reference_key,
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
        )
        sec_proofs = sec_snapshot_coverage_proofs(
            source_request,
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
            passages=(sec_passage, listing_passage),
        )

        issuer_transport = session.official_transport("issuer_document")
        issuer_snapshot = OfficialIssuerEvidenceAdapter(
            allowed_hosts=source_plan.trusted_issuer_hosts,
            transport=issuer_transport,
            clock=issuer_transport.clock,
        ).collect(
            source_request,
            source_plan.issuer_sources,
        )
        issuer_passages = official_snapshot_pipeline_inputs(issuer_snapshot)
        issuer_proofs = official_snapshot_coverage_proofs(issuer_snapshot)

        clinical_identity = source_plan.clinical_trial_search
        clinical_transport = session.clinical_trials_transport()
        trial_snapshot = ClinicalTrialsCollector(
            ClinicalTrialsSettings(),
            transport=clinical_transport,
            clock=clinical_transport.clock,
        ).collect(
            source_request,
            clinical_identity,
        )
        clinical_passages = clinical_trials_pipeline_inputs(trial_snapshot)
        clinical_proof = clinical_trials_coverage_proof(trial_snapshot)

        regulatory_transport = session.official_transport("regulatory_document")
        regulatory_snapshot = FDARegulatoryEvidenceAdapter(
            allowed_hosts=source_plan.regulatory_allowed_hosts,
            transport=regulatory_transport,
            clock=regulatory_transport.clock,
        ).collect(
            source_request,
            source_plan.regulatory_sources,
        )
        regulatory_program_names = tuple(
            dict.fromkeys(
                (
                    source_plan.clinical_trial_search.program_name,
                    *source_plan.clinical_trial_search.search_terms,
                )
            )
        )
        regulatory_passages = official_snapshot_pipeline_inputs(
            regulatory_snapshot,
            regulatory_program_names=regulatory_program_names,
        )
        regulatory_proofs = official_snapshot_coverage_proofs(
            regulatory_snapshot,
            regulatory_program_names=regulatory_program_names,
        )

        companyfacts_transport = session.sec_transport()
        companyfacts_snapshot = SecCompanyFactsCollector(
            SecCompanyFactsSettings(
                user_agent="Investment Research OS research@example.com"
            ),
            transport=companyfacts_transport,
            clock=companyfacts_transport.clock,
        ).collect(source_request)
        session.assert_all_consumed()
        self.assertEqual(
            Counter(response.role for response in capture.responses),
            Counter(
                {
                    "sec_security_registry": 1,
                    "sec_submissions_root": 1,
                    "sec_companyfacts": 1,
                    "sec_filing_document": len(selection.selected_filings),
                    "sec_filing_index": len(selection.selected_filings),
                    "issuer_document": 1,
                    "clinical_trials_page": 1,
                    "regulatory_document": 1,
                }
            ),
        )
        self.assertEqual(
            capture.receipt.provenance_mode,
            "operator_supplied_unverified",
        )
        self.assertEqual(
            capture.receipt.capture_content_hash,
            capture.content_hash,
        )
        self.assertEqual(capture.plan.content_hash, source_plan.content_hash)
        financing_core_passages, metrics = companyfacts_pipeline_inputs(
            companyfacts_snapshot
        )
        capital_passage = sec_financing_passage_pipeline_input(
            source_request,
            SecExactPassageExtractor().extract(
                resolved_sec_sources["financing"].document,
                sec_plans["financing"].exact_text,
            ),
            reference_key=sec_plans["financing"].reference_key,
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
        )
        filing_metrics = financing_field_metrics(
            capital_passage.reference_key,
            (resolved_sec_sources["financing"].document.report_date or CUTOFF.date()),
        )
        (
            financing_passages,
            financing_proof,
            financing_facts,
        ) = sec_financing_coverage_inputs(
            source_request,
            companyfacts=companyfacts_snapshot,
            submissions=submissions,
            selection=selection,
            documents=documents,
            exhibits=exhibits,
            core_passages=financing_core_passages,
            core_metrics=metrics,
            filing_passages=(capital_passage,),
            filing_metrics=filing_metrics,
            field_evidence=tuple(
                FinancingFieldEvidence(
                    field_id=field_id,
                    outcome=("complete" if field_id == "basic_shares" else "absent"),
                    evidence_reference_keys=(
                        ("sec-companyfacts:basic_shares_outstanding")
                        if field_id == "basic_shares"
                        else f"financing-metric:{field_id}",
                    ),
                )
                for field_id in FINANCING_FIELD_IDS
            ),
        )

        all_passages = (
            sec_passage,
            listing_passage,
            *issuer_passages,
            *clinical_passages,
            *regulatory_passages,
            *financing_passages,
        )
        result = PrimarySourcePipeline().assemble(
            request=source_request,
            profile=derive_biotech_eligibility_profile(
                request=source_request,
                registered_security=registry_security,
                submissions=submissions,
                issuer=issuer_snapshot,
                clinical_trials=trial_snapshot,
                companyfacts=companyfacts_snapshot,
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
            metrics=(*metrics, *filing_metrics),
            catalysts=(
                NormalizedCatalystFact(
                    reference_key=case.catalyst_reference_key,
                    source_class="clinical",
                    event=case.catalyst_event,
                    program=case.clinical_program,
                    basis="clinical",
                    status="expected",
                    window_start=case.catalyst_window_start,
                    window_end=case.catalyst_window_end,
                    supporting_passage_keys=(
                        f"clinical-trial:{case.clinical_nct_id}",
                        f"issuer:{case.issuer_source_key}:{case.issuer_passage_key}",
                    ),
                ),
            ),
            risks=tuple(
                NormalizedRiskFact(
                    reference_key=(f"financing-semantic-outcome:{fact.field_id}"),
                    source_class="financing",
                    title=(f"Financing semantic outcome: {fact.field_id}"),
                    risk_type=f"financing_semantic:{fact.field_id}",
                    severity="informational",
                    status=fact.outcome,
                    supporting_passage_keys=(fact.supporting_passage_keys),
                )
                for fact in financing_facts
            ),
            regulatory_program_names=regulatory_program_names,
        )

        run_repository = InMemoryResearchRunRepository()
        run = ResearchRunWorkflow(
            repository=run_repository,
            eligibility_source=FixedEligibilitySource(result.eligibility_snapshot),
            clock=lambda: CREATED_AT,
        ).create(
            AuthenticatedOperator(OPERATOR_ID),
            {
                "question_type": ("biotech_moonshot_catalyst_assessment"),
                "security_id": case.security_id,
                "as_of_cutoff": CUTOFF.isoformat(),
                "workflow_config_version": ("biotech-moonshot-catalyst-v1"),
            },
        )
        plan_binding = plan_repository.bind_to_run(source_plan, run)
        bundle = EvidenceBundleWorkflow(
            research_run_repository=run_repository,
            bundle_repository=InMemoryEvidenceBundleRepository(),
            evidence_source=FixedEvidenceSource(result.bundle_candidate),
            clock=lambda: CREATED_AT,
        ).materialize(AuthenticatedOperator(OPERATOR_ID), run.id)

        self.assertTrue(run.eligibility.eligible)
        self.assertTrue(bundle.grader_ready)
        self.assertEqual(
            {item.source_class for item in bundle.manifest},
            {"sec", "issuer", "clinical", "regulatory", "financing"},
        )
        self.assertEqual(len(bundle.metrics), 11)
        self.assertEqual(len(bundle.risks), 8)
        self.assertEqual(
            {
                risk.status
                for risk in bundle.risks
                if risk.risk_type.startswith("financing_semantic:")
            },
            {"complete", "absent"},
        )
        self.assertEqual(
            next(
                metric.value
                for metric in bundle.metrics
                if metric.metric_key == "cash_and_cash_equivalents"
            ),
            case.expected_cash,
        )
        self.assertEqual(
            next(
                metric.value
                for metric in bundle.metrics
                if metric.metric_key == "operating_cash_used"
            ),
            case.expected_operating_cash_used,
        )
        self.assertEqual(
            sum(
                item.source_class == "clinical" and item.item_kind == "passage"
                for item in bundle.manifest
            ),
            case.expected_clinical_passages,
        )
        self.assertEqual(len(bundle.catalysts), 1)
        self.assertEqual(bundle.gaps, ())
        self.assertEqual(len(bundle.content_hash), 64)
        self.assertEqual(len(source_plan.content_hash), 64)
        self.assertEqual(
            plan_binding.plan_content_hash,
            source_plan.content_hash,
        )
        self.assertEqual(
            plan_repository.get_for_run(OPERATOR_ID, run.id),
            plan_binding,
        )
        return run, bundle, capture

    def test_generic_offline_sources_create_eligible_immutable_bundle(
        self,
    ) -> None:
        self._run_fixture(PLATFORM_CASE)

    def test_materially_different_single_asset_fixture_uses_same_pipeline(
        self,
    ) -> None:
        _run, bundle, _capture = self._run_fixture(SINGLE_ASSET_CASE)

        self.assertEqual(
            bundle.catalysts[0].program,
            "Lead-901 pivotal programme",
        )
        self.assertEqual(
            bundle.catalysts[0].event,
            "Lead-901 Phase 3 top-line data",
        )

    def test_source_plan_cannot_self_authorize_issuer_origin(self) -> None:
        candidate = source_plan_value(PLATFORM_CASE)
        candidate["issuer_sources"][0]["source_url"] = (
            "https://untrusted.example/news/programme"
        )

        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "origin is not trusted",
        ):
            bind_primary_source_plan(
                load_primary_source_plan(
                    json.dumps(candidate).encode(),
                ),
                request(PLATFORM_CASE),
                trusted_issuer_hosts=(PLATFORM_CASE.issuer_trusted_hosts),
            )


if __name__ == "__main__":
    unittest.main()
