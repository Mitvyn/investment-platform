from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path
import unittest

from investment_research_os.research_runs import (
    EligibilityResult,
    QUESTION_TYPE,
    QUESTION_TYPE_VERSION,
    ResearchRun,
    SecurityIdentity,
    THESIS_CONTRACT_ID,
    WORKFLOW_CONFIG_VERSION,
)
from workers.primary_sources.models import PrimarySourceRequest
from workers.primary_sources.plans import (
    InMemoryPrimarySourcePlanRepository,
    PRIMARY_SOURCE_PLAN_V1,
    PRIMARY_SOURCE_PLAN_V2,
    PRIMARY_SOURCE_PLAN_V3,
    PrimarySourcePlanError,
    bind_primary_source_plan,
    load_primary_source_plan,
    resolve_sec_passage_sources,
)
from workers.sec.documents import (
    SecFilingDocument,
    SecFilingDocumentSnapshot,
)


OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
SECURITY_ID = "56ed2444-fb42-5e40-97b6-000163c5a019"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)


def request() -> PrimarySourceRequest:
    return PrimarySourceRequest(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik="0001601830",
        issuer_name="Recursion Pharmaceuticals, Inc.",
        primary_listing_exchange="NASDAQ",
        as_of_cutoff=CUTOFF,
    )


def locator(
    *,
    source_key: str,
    requirement_id: str,
    source_url: str,
    passage_key: str,
) -> dict[str, object]:
    return {
        "source_key": source_key,
        "requirement_id": requirement_id,
        "title": f"{source_key} title",
        "source_url": source_url,
        "publication_time": "2026-05-05T20:00:00Z",
        "effective_date": "2026-05-05",
        "coverage_role": "required",
        "coverage_mode": "all",
        "passages": [
            {
                "passage_key": passage_key,
                "locator": "main > p",
                "exact_text": f"{source_key} exact evidence.",
            }
        ],
    }


def value() -> dict[str, object]:
    return {
        "contract_version": PRIMARY_SOURCE_PLAN_V1,
        "plan_id": "2a66e345-b193-4f61-80a1-f604885c7b15",
        "revision": 1,
        "effective_at": "2026-05-05T00:00:00Z",
        "question_type": QUESTION_TYPE,
        "workflow_config_version": WORKFLOW_CONFIG_VERSION,
        "security": {
            "security_id": SECURITY_ID,
            "cik": "0001601830",
            "issuer_name": "Recursion Pharmaceuticals, Inc.",
            "primary_listing_exchange": "NASDAQ",
        },
        "sec_passages": [
            {
                "reference_key": "sec-required-filings",
                "role": "required_filing",
                "selected_form": "10-Q",
                "exact_text": "Required filing evidence.",
            },
            {
                "reference_key": "sec-identity-and-listing",
                "role": "identity_listing",
                "selected_form": "10-Q",
                "exact_text": (
                    "Our common stock is listed on the Nasdaq Global Select Market."
                ),
            },
            {
                "reference_key": "financing:capital-structure",
                "role": "financing",
                "selected_form": "10-Q",
                "exact_text": "Capital structure evidence.",
            },
        ],
        "issuer_sources": [
            locator(
                source_key="pipeline-update",
                requirement_id="issuer_pipeline",
                source_url=(
                    "https://ir.recursion.com/news-releases/"
                    "news-release-details/example"
                ),
                passage_key="programme",
            )
        ],
        "clinical_trial_search": {
            "program_name": "REC-4881",
            "search_terms": ["REC-4881"],
            "allowed_sponsor_names": [
                "Recursion Pharmaceuticals, Inc.",
            ],
        },
        "regulatory_sources": [
            locator(
                source_key="regulatory-update",
                requirement_id="us_regulatory",
                source_url="https://www.fda.gov/drugs/example",
                passage_key="regulatory-status",
            )
        ],
    }


def raw(candidate: dict[str, object] | None = None) -> bytes:
    return json.dumps(candidate or value()).encode()


def v3_value() -> dict[str, object]:
    candidate = value()
    candidate["contract_version"] = PRIMARY_SOURCE_PLAN_V3
    candidate["revision"] = 3
    candidate["sec_passages"].append(
        {
            "reference_key": "corporate-action:share-basis",
            "role": "corporate_action",
            "selected_form": "10-Q",
            "selected_accession_number": "0001601830-26-000078",
            "exact_text": (
                "No stock split or reverse stock split occurred during the period."
            ),
        }
    )
    return candidate


def document(form: str, accession_suffix: int) -> SecFilingDocument:
    body = f"<html>{form}:{accession_suffix}</html>"
    accession = f"0001601830-26-{accession_suffix:06d}"
    return SecFilingDocument(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik="0001601830",
        accession_number=accession,
        form=form,
        filing_date=date(2026, 5, 5),
        report_date=date(2026, 3, 31),
        primary_document=f"filing-{accession_suffix}.htm",
        source_class="sec_filing",
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1601830/"
            f"{accession.replace('-', '')}/filing-{accession_suffix}.htm"
        ),
        published_at=datetime(2026, 5, 5, 20, tzinfo=UTC),
        publication_date=date(2026, 5, 5),
        retrieved_at=datetime(2026, 5, 7, 1, tzinfo=UTC),
        content_sha256=hashlib.sha256(body.encode()).hexdigest(),
        content_text=body,
    )


def documents(
    *items: SecFilingDocument,
) -> SecFilingDocumentSnapshot:
    return SecFilingDocumentSnapshot(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik="0001601830",
        as_of_cutoff=CUTOFF,
        policy_version="biotech-required-sec-filings-v1",
        documents=tuple(items),
    )


def research_run() -> ResearchRun:
    return ResearchRun(
        id="127e4c9d-b2d1-4e7c-9bbc-61f5a7b04073",
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        security_identity=SecurityIdentity(
            id=SECURITY_ID,
            cik="0001601830",
            issuer_name="Recursion Pharmaceuticals, Inc.",
            symbol="RXRX",
            primary_listing_exchange="NASDAQ",
        ),
        question_type=QUESTION_TYPE,
        question_type_version=QUESTION_TYPE_VERSION,
        workflow_config_version=WORKFLOW_CONFIG_VERSION,
        thesis_contract_id=THESIS_CONTRACT_ID,
        as_of_cutoff=CUTOFF,
        operator_focus_original=None,
        operator_focus_normalized=None,
        status="eligible",
        idempotency_key="source-plan-test",
        eligibility=EligibilityResult(
            policy_version="biotech-security-eligibility-v1",
            eligible=True,
            checks=(),
            evaluated_at=CUTOFF,
        ),
        created_at=CUTOFF,
    )


class PrimarySourcePlanTests(unittest.TestCase):
    def test_v3_accepts_one_accession_qualified_corporate_action_passage(
        self,
    ) -> None:
        candidate = v3_value()

        loaded = load_primary_source_plan(raw(candidate))

        self.assertEqual(loaded.contract_version, PRIMARY_SOURCE_PLAN_V3)
        corporate_action = next(
            passage
            for passage in loaded.sec_passages
            if passage.role == "corporate_action"
        )
        self.assertEqual(
            corporate_action.selected_accession_number,
            "0001601830-26-000078",
        )
        self.assertEqual(corporate_action.selected_form, "10-Q")
        self.assertEqual(
            corporate_action.exact_text,
            "No stock split or reverse stock split occurred during the period.",
        )

    def test_v2_rejects_corporate_action_passage_role(self) -> None:
        candidate = v3_value()
        candidate["contract_version"] = PRIMARY_SOURCE_PLAN_V2

        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "SEC passage role is invalid",
        ):
            load_primary_source_plan(raw(candidate))

    def test_v3_requires_exactly_one_corporate_action_passage(self) -> None:
        missing = v3_value()
        missing["sec_passages"] = [
            passage
            for passage in missing["sec_passages"]
            if passage["role"] != "corporate_action"
        ]
        duplicate = v3_value()
        second = deepcopy(duplicate["sec_passages"][-1])
        second["reference_key"] = "corporate-action:second-share-basis"
        duplicate["sec_passages"].append(second)

        for candidate in (missing, duplicate):
            with self.subTest(candidate=candidate):
                with self.assertRaisesRegex(
                    PrimarySourcePlanError,
                    "SEC passage v3 cardinality is invalid",
                ):
                    load_primary_source_plan(raw(candidate))

    def test_v3_corporate_action_requires_exact_accession_form_and_text(
        self,
    ) -> None:
        cases = (
            (
                {"selected_accession_number": None},
                "requires selected accession",
            ),
            (
                {"selected_accession_number": "0001601830-26-78"},
                "selected accession number is invalid",
            ),
            (
                {"selected_form": "DEF 14A"},
                "selected form is invalid",
            ),
            (
                {"exact_text": "   "},
                "exact passage is required",
            ),
        )
        for changes, expected_error in cases:
            with self.subTest(changes=changes):
                candidate = v3_value()
                corporate_action = candidate["sec_passages"][-1]
                if (
                    "selected_accession_number" in changes
                    and changes["selected_accession_number"] is None
                ):
                    corporate_action.pop("selected_accession_number")
                else:
                    corporate_action.update(changes)
                with self.assertRaisesRegex(
                    PrimarySourcePlanError,
                    expected_error,
                ):
                    load_primary_source_plan(raw(candidate))

    def test_v3_resolves_corporate_action_by_exact_form_and_accession(
        self,
    ) -> None:
        candidate = v3_value()
        for passage in candidate["sec_passages"]:
            passage["selected_accession_number"] = (
                "0001601830-26-000079"
                if passage["role"] == "corporate_action"
                else "0001601830-26-000078"
            )
        plan = bind_primary_source_plan(
            load_primary_source_plan(raw(candidate)),
            request(),
            trusted_issuer_hosts=("ir.recursion.com",),
        )

        resolved = resolve_sec_passage_sources(
            plan,
            documents(document("10-Q", 78), document("10-Q", 79)),
        )

        corporate_action = next(
            item for item in resolved if item.plan.role == "corporate_action"
        )
        self.assertEqual(
            corporate_action.document.accession_number,
            "0001601830-26-000079",
        )

    def test_v3_bind_revalidates_corporate_action_cardinality(self) -> None:
        loaded = load_primary_source_plan(raw(v3_value()))
        forged = replace(
            loaded,
            sec_passages=tuple(
                passage
                for passage in loaded.sec_passages
                if passage.role != "corporate_action"
            ),
        )

        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "integrity is invalid",
        ):
            bind_primary_source_plan(
                forged,
                request(),
                trusted_issuer_hosts=("ir.recursion.com",),
            )

    def test_loads_accession_qualified_literal_rxrx_plan_v2(self) -> None:
        loaded = load_primary_source_plan(
            Path(
                "tests/fixtures/primary_sources/rxrx-primary-source-plan-v2.json"
            ).read_bytes()
        )

        self.assertEqual(
            loaded.content_hash,
            "4b13ad2a8dcb77e8511c49dd4edb29019d3d619a73fc37edb8a53f5254156c91",
        )
        self.assertEqual(loaded.revision, 2)
        self.assertEqual(len(loaded.sec_passages), 14)
        self.assertEqual(
            len({passage.selected_accession_number for passage in loaded.sec_passages}),
            10,
        )
        self.assertTrue(
            all(
                passage.selected_accession_number is not None
                for passage in loaded.sec_passages
            )
        )

    def test_loads_and_binds_existing_domain_types(self) -> None:
        loaded = load_primary_source_plan(raw())
        plan = bind_primary_source_plan(
            loaded,
            request(),
            trusted_issuer_hosts=("ir.recursion.com",),
        )

        self.assertEqual(loaded.contract_version, PRIMARY_SOURCE_PLAN_V1)
        self.assertEqual(loaded.security_id, SECURITY_ID)
        self.assertEqual(loaded.question_type_version, f"{QUESTION_TYPE}.v1")
        self.assertEqual(plan.operator_id, OPERATOR_ID)
        self.assertEqual(plan.as_of_cutoff, CUTOFF)
        self.assertEqual(
            plan.clinical_trial_search.search_terms,
            ("REC-4881",),
        )
        self.assertEqual(plan.regulatory_allowed_hosts, ("www.fda.gov",))
        self.assertEqual(len(plan.content_hash), 64)
        self.assertEqual(
            plan.content_hash,
            "2ace6c6783049d6b6698373f68904b24e0d7c9a7e4af9bfd8056eec85da8d809",
        )

    def test_v2_accepts_multiple_field_specific_financing_passages(
        self,
    ) -> None:
        candidate = value()
        candidate["contract_version"] = PRIMARY_SOURCE_PLAN_V2
        candidate["revision"] = 2
        candidate["sec_passages"].append(
            {
                "reference_key": "financing:rsus",
                "role": "financing",
                "selected_form": "10-Q",
                "exact_text": "RSU activity evidence.",
            }
        )

        loaded = load_primary_source_plan(raw(candidate))
        plan = bind_primary_source_plan(
            loaded,
            request(),
            trusted_issuer_hosts=("ir.recursion.com",),
        )

        self.assertEqual(plan.loaded.contract_version, PRIMARY_SOURCE_PLAN_V2)
        self.assertEqual(
            [
                passage.reference_key
                for passage in plan.sec_passages
                if passage.role == "financing"
            ],
            ["financing:capital-structure", "financing:rsus"],
        )

    def test_v2_resolves_same_form_financing_passages_by_accession(
        self,
    ) -> None:
        candidate = value()
        candidate["contract_version"] = PRIMARY_SOURCE_PLAN_V2
        candidate["revision"] = 2
        candidate["sec_passages"][2] = {
            "reference_key": "financing:atm-2024",
            "role": "financing",
            "selected_form": "424B5",
            "selected_accession_number": "0001601830-24-000088",
            "exact_text": "2024 ATM evidence.",
        }
        candidate["sec_passages"].append(
            {
                "reference_key": "financing:atm-2026",
                "role": "financing",
                "selected_form": "424B5",
                "selected_accession_number": "0001601830-26-000041",
                "exact_text": "2026 ATM evidence.",
            }
        )
        plan = bind_primary_source_plan(
            load_primary_source_plan(raw(candidate)),
            request(),
            trusted_issuer_hosts=("ir.recursion.com",),
        )
        snapshot = documents(
            document("10-Q", 40),
            replace(
                document("424B5", 88),
                accession_number="0001601830-24-000088",
            ),
            replace(
                document("424B5", 41),
                accession_number="0001601830-26-000041",
            ),
        )

        resolved = resolve_sec_passage_sources(plan, snapshot)

        self.assertEqual(
            {
                item.plan.reference_key: item.document.accession_number
                for item in resolved
                if item.plan.role == "financing"
            },
            {
                "financing:atm-2024": "0001601830-24-000088",
                "financing:atm-2026": "0001601830-26-000041",
            },
        )

    def test_v2_bind_revalidates_financing_cardinality(self) -> None:
        candidate = value()
        candidate["contract_version"] = PRIMARY_SOURCE_PLAN_V2
        loaded = load_primary_source_plan(raw(candidate))
        forged = replace(
            loaded,
            sec_passages=tuple(
                passage
                for passage in loaded.sec_passages
                if passage.role != "financing"
            ),
        )

        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "integrity is invalid",
        ):
            bind_primary_source_plan(
                forged,
                request(),
                trusted_issuer_hosts=("ir.recursion.com",),
            )

    def test_hash_and_order_are_semantic(self) -> None:
        first = value()
        first["issuer_sources"].append(
            locator(
                source_key="capital-update",
                requirement_id="issuer_pipeline",
                source_url="https://ir.recursion.com/news/capital",
                passage_key="cash",
            )
        )
        second = deepcopy(first)
        second["issuer_sources"].reverse()
        second["sec_passages"].reverse()
        second["clinical_trial_search"]["search_terms"] = [
            "REC-4881",
            "AX-4881",
        ]
        first["clinical_trial_search"]["search_terms"] = [
            "AX-4881",
            "REC-4881",
        ]
        second["clinical_trial_search"]["allowed_sponsor_names"] = [
            "Recursion",
            "Recursion Pharmaceuticals, Inc.",
        ]
        first["clinical_trial_search"]["allowed_sponsor_names"] = [
            "Recursion Pharmaceuticals, Inc.",
            "Recursion",
        ]

        first_plan = load_primary_source_plan(raw(first))
        second_plan = load_primary_source_plan(
            json.dumps(second, indent=4, sort_keys=True).encode()
        )

        self.assertEqual(first_plan, second_plan)
        self.assertEqual(
            tuple(source.source_key for source in first_plan.issuer_sources),
            ("capital-update", "pipeline-update"),
        )

    def test_binding_rejects_identity_cutoff_and_self_authorized_host(
        self,
    ) -> None:
        for field_name, invalid in {
            "security_id": "11111111-1111-4111-8111-111111111111",
            "cik": "0000000001",
            "issuer_name": "Another Issuer, Inc.",
            "primary_listing_exchange": "NYSE",
        }.items():
            with self.subTest(field_name=field_name):
                candidate = value()
                candidate["security"][field_name] = invalid
                loaded = load_primary_source_plan(raw(candidate))
                with self.assertRaisesRegex(
                    PrimarySourcePlanError,
                    "identity does not match request",
                ):
                    bind_primary_source_plan(
                        loaded,
                        request(),
                        trusted_issuer_hosts=("ir.recursion.com",),
                    )

        candidate = value()
        candidate["effective_at"] = "2026-05-07T00:00:00Z"
        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "effective after request cutoff",
        ):
            bind_primary_source_plan(
                load_primary_source_plan(raw(candidate)),
                request(),
                trusted_issuer_hosts=("ir.recursion.com",),
            )

        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "origin is not trusted",
        ):
            bind_primary_source_plan(
                load_primary_source_plan(raw()),
                request(),
                trusted_issuer_hosts=("unrelated.example",),
            )

    def test_rejects_invalid_json_duplicate_fields_and_contract_drift(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "JSON is invalid",
        ):
            load_primary_source_plan(b"{")

        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "duplicate fields",
        ):
            load_primary_source_plan(
                b'{"contract_version":"primary_source_plan.v1",'
                b'"contract_version":"primary_source_plan.v1"}'
            )

        candidate = value()
        candidate["contract_version"] = "primary_source_plan.v4"
        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "version is unsupported",
        ):
            load_primary_source_plan(raw(candidate))

        candidate = value()
        candidate["ticker"] = "RXRX"
        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "fields are invalid",
        ):
            load_primary_source_plan(raw(candidate))

    def test_rejects_wrong_workflow_requirements_and_origins(self) -> None:
        candidate = value()
        candidate["workflow_config_version"] = "missing"
        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "unsupported or inactive",
        ):
            load_primary_source_plan(raw(candidate))

        candidate = value()
        candidate["issuer_sources"][0]["requirement_id"] = "us_regulatory"
        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "issuer source requirement is invalid",
        ):
            load_primary_source_plan(raw(candidate))

        candidate = value()
        candidate["regulatory_sources"][0]["source_url"] = (
            "https://investors.example.com/regulatory"
        )
        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "regulatory source origin is invalid",
        ):
            load_primary_source_plan(raw(candidate))

        for lane in ("issuer_sources", "regulatory_sources"):
            with self.subTest(lane=lane):
                candidate = value()
                candidate[lane][0]["source_url"] = (
                    "https://www.fda.gov:8443/drugs/example"
                    if lane == "regulatory_sources"
                    else "https://ir.recursion.com:8443/news/example"
                )
                with self.assertRaisesRegex(
                    PrimarySourcePlanError,
                    "origin is invalid",
                ):
                    load_primary_source_plan(raw(candidate))

    def test_accepts_explicit_accessdata_fda_regulatory_origin(self) -> None:
        candidate = value()
        candidate["regulatory_sources"][0]["source_url"] = (
            "https://www.accessdata.fda.gov/scripts/opdlisting/oopd/"
            "detailedIndex.cfm?cfgridkey=817621"
        )

        plan = load_primary_source_plan(raw(candidate))

        self.assertEqual(
            plan.regulatory_sources[0].source_url,
            (
                "https://www.accessdata.fda.gov/scripts/opdlisting/oopd/"
                "detailedIndex.cfm?cfgridkey=817621"
            ),
        )

    def test_accepts_explicit_precision_fda_regulatory_origin(self) -> None:
        candidate = value()
        candidate["regulatory_sources"][0]["source_url"] = (
            "https://precision.fda.gov/ginas/app/api/v1/"
            "substances(5J61HSP0QJ)?view=internal"
        )

        plan = load_primary_source_plan(raw(candidate))

        self.assertEqual(
            plan.regulatory_sources[0].source_url,
            (
                "https://precision.fda.gov/ginas/app/api/v1/"
                "substances(5J61HSP0QJ)?view=internal"
            ),
        )

    def test_rejects_duplicate_or_missing_acquisition_inputs(self) -> None:
        candidate = value()
        candidate["issuer_sources"].append(deepcopy(candidate["issuer_sources"][0]))
        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "source keys must be unique",
        ):
            load_primary_source_plan(raw(candidate))

        candidate = value()
        candidate["sec_passages"].append(deepcopy(candidate["sec_passages"][0]))
        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "reference keys must be unique",
        ):
            load_primary_source_plan(raw(candidate))

        candidate = value()
        duplicate_role = deepcopy(candidate["sec_passages"][0])
        duplicate_role["reference_key"] = "another-required-filing"
        candidate["sec_passages"].append(duplicate_role)
        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "roles must appear exactly once",
        ):
            load_primary_source_plan(raw(candidate))

        candidate = value()
        candidate["sec_passages"] = [
            passage
            for passage in candidate["sec_passages"]
            if passage["role"] != "financing"
        ]
        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "required roles are missing",
        ):
            load_primary_source_plan(raw(candidate))

        for field_name in (
            "sec_passages",
            "issuer_sources",
            "regulatory_sources",
        ):
            with self.subTest(field_name=field_name):
                candidate = value()
                candidate[field_name] = []
                with self.assertRaisesRegex(
                    PrimarySourcePlanError,
                    "must not be empty",
                ):
                    load_primary_source_plan(raw(candidate))

    def test_loaded_plan_is_frozen_and_content_changes_hash(self) -> None:
        loaded = load_primary_source_plan(raw())
        changed = value()
        changed["issuer_sources"][0]["passages"][0]["exact_text"] = (
            "Corrected exact evidence."
        )

        with self.assertRaises(FrozenInstanceError):
            loaded.revision = 2  # type: ignore[misc]
        self.assertNotEqual(
            loaded.content_hash,
            load_primary_source_plan(raw(changed)).content_hash,
        )

    def test_binding_revalidates_loaded_plan_integrity(self) -> None:
        loaded = load_primary_source_plan(raw())
        for forged in (
            replace(loaded, content_hash="0" * 64),
            replace(loaded, question_type_version="forged"),
        ):
            with self.subTest(forged=forged):
                with self.assertRaisesRegex(
                    PrimarySourcePlanError,
                    "loaded source plan integrity is invalid",
                ):
                    bind_primary_source_plan(
                        forged,
                        request(),
                        trusted_issuer_hosts=("ir.recursion.com",),
                    )

    def test_sec_passage_resolution_honors_form_and_rejects_ambiguity(
        self,
    ) -> None:
        candidate = value()
        candidate["sec_passages"][0]["selected_form"] = "10-K"
        plan = bind_primary_source_plan(
            load_primary_source_plan(raw(candidate)),
            request(),
            trusted_issuer_hosts=("ir.recursion.com",),
        )
        quarterly = document("10-Q", 40)
        annual = document("10-K", 30)

        resolved = resolve_sec_passage_sources(
            plan,
            documents(annual, quarterly),
        )

        by_role = {item.plan.role: item.document for item in resolved}
        self.assertEqual(by_role["required_filing"], annual)
        self.assertEqual(by_role["identity_listing"], quarterly)
        self.assertEqual(by_role["financing"], quarterly)

        candidate["sec_passages"][0]["selected_form"] = "8-K"
        ambiguous_plan = bind_primary_source_plan(
            load_primary_source_plan(raw(candidate)),
            request(),
            trusted_issuer_hosts=("ir.recursion.com",),
        )
        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "selected form is missing or ambiguous",
        ):
            resolve_sec_passage_sources(
                ambiguous_plan,
                documents(
                    annual,
                    quarterly,
                    document("8-K", 41),
                    document("8-K", 42),
                ),
            )

    def test_repository_preserves_plan_revision_and_run_binding(
        self,
    ) -> None:
        plan = bind_primary_source_plan(
            load_primary_source_plan(raw()),
            request(),
            trusted_issuer_hosts=("ir.recursion.com",),
        )
        repository = InMemoryPrimarySourcePlanRepository()

        self.assertEqual(repository.save(plan), plan.loaded)
        self.assertEqual(
            repository.get_plan(plan.loaded.plan_id, 1),
            plan.loaded,
        )
        binding = repository.bind_to_run(
            plan,
            research_run(),
        )

        self.assertEqual(binding.plan_id, plan.loaded.plan_id)
        self.assertEqual(binding.plan_revision, 1)
        self.assertEqual(binding.plan_content_hash, plan.content_hash)
        self.assertEqual(
            repository.get_for_run(
                OPERATOR_ID,
                "127e4c9d-b2d1-4e7c-9bbc-61f5a7b04073",
            ),
            binding,
        )
        self.assertEqual(repository.save(plan), plan.loaded)
        self.assertEqual(
            repository.bind_to_run(
                plan,
                research_run(),
            ),
            binding,
        )

        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "Research Run does not match source plan",
        ):
            repository.bind_to_run(
                plan,
                replace(
                    research_run(),
                    security_id=("11111111-1111-4111-8111-111111111111"),
                ),
            )

        changed = value()
        changed["issuer_sources"][0]["passages"][0]["exact_text"] = (
            "Corrected source text."
        )
        conflicting = bind_primary_source_plan(
            load_primary_source_plan(raw(changed)),
            request(),
            trusted_issuer_hosts=("ir.recursion.com",),
        )
        with self.assertRaisesRegex(
            PrimarySourcePlanError,
            "conflicting immutable source plan revision",
        ):
            repository.save(conflicting)


if __name__ == "__main__":
    unittest.main()
