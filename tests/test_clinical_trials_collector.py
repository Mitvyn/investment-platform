from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import unittest

from workers.clinical_trials.collector import (
    ClinicalTrialsCollector,
    ClinicalTrialsCollectorError,
    ClinicalTrialsSettings,
    ClinicalTrialsTransportResponse,
    clinical_trials_coverage_proof,
    clinical_trials_pipeline_inputs,
)
from workers.clinical_trials.models import ClinicalTrialSearchIdentity
from workers.primary_sources.models import PrimarySourceRequest


FIXTURE_ROOT = Path("tests/fixtures/primary_sources")
OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
SECURITY_ID = "f594edb2-7fff-4e40-9c26-2c06bcbecb91"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)


class FixtureTransport:
    def __init__(
        self,
        responses: dict[str, bytes],
        *,
        final_urls: dict[str, str] | None = None,
    ) -> None:
        self.responses = responses
        self.final_urls = final_urls or {}
        self.requests: list[tuple[str, dict[str, str]]] = []

    def request(self, url: str, *, headers):
        self.requests.append((url, dict(headers)))
        return ClinicalTrialsTransportResponse(
            body=self.responses[url],
            status=200,
            headers={"Content-Type": "application/json"},
            final_url=self.final_urls.get(url, url),
        )


def primary_source_request() -> PrimarySourceRequest:
    return PrimarySourceRequest(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik="0001601830",
        issuer_name="Example Therapeutics, Inc.",
        primary_listing_exchange="NASDAQ",
        as_of_cutoff=CUTOFF,
    )


def studies_url(*, page_token: str | None = None) -> str:
    url = (
        "https://clinicaltrials.gov/api/v2/studies"
        "?format=json&pageSize=100&countTotal=true"
        "&query.term=%22Asset+Alpha%22+OR+%22Asset+Beta%22"
    )
    if page_token is not None:
        return f"{url}&pageToken={page_token}"
    return url


def history_summary_url(nct_id: str) -> str:
    return (
        f"https://clinicaltrials.gov/api/int/studies/{nct_id}?history=true"
    )


def history_version_url(nct_id: str, version: int) -> str:
    return (
        f"https://clinicaltrials.gov/api/int/studies/{nct_id}/history/{version}"
    )


class ClinicalTrialsCollectorTests(unittest.TestCase):
    def test_accepts_only_authoritative_clinical_trials_origin(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "ClinicalTrials.gov base URL is unsupported",
        ):
            ClinicalTrialsSettings(base_url="https://example.com")

        body = (
            FIXTURE_ROOT / "clinical-trials-programme.json"
        ).read_bytes()
        collector = ClinicalTrialsCollector(
            ClinicalTrialsSettings(),
            transport=FixtureTransport(
                {studies_url(): body},
                final_urls={
                    studies_url(): "https://example.com/api/v2/studies"
                },
            ),
        )
        with self.assertRaisesRegex(
            ClinicalTrialsCollectorError,
            "studies response redirected",
        ):
            collector.collect(
                primary_source_request(),
                ClinicalTrialSearchIdentity(
                    program_name="Example oncology programme",
                    search_terms=("Asset Alpha", "Asset Beta"),
                ),
            )

    def test_collects_programme_studies_as_source_covered_snapshot(self) -> None:
        body = (
            FIXTURE_ROOT / "clinical-trials-programme.json"
        ).read_bytes()
        source_url = studies_url()
        transport = FixtureTransport({source_url: body})
        collector = ClinicalTrialsCollector(
            ClinicalTrialsSettings(),
            transport=transport,
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        result = collector.collect(
            primary_source_request(),
            ClinicalTrialSearchIdentity(
                program_name="Example oncology programme",
                search_terms=("Asset Alpha", "Asset Beta"),
            ),
        )

        self.assertEqual(result.operator_id, OPERATOR_ID)
        self.assertEqual(result.security_id, SECURITY_ID)
        self.assertEqual(result.cik, "0001601830")
        self.assertEqual(result.program_name, "Example oncology programme")
        self.assertEqual(result.as_of_cutoff, CUTOFF)
        self.assertEqual(result.policy_version, "clinical-trials-source-v2")
        self.assertEqual(result.coverage.status, "covered")
        self.assertEqual(
            result.coverage.reason_codes,
            ("clinical_trials_source_covered",),
        )
        self.assertEqual(
            [study.nct_id for study in result.included_studies],
            ["NCT06000001", "NCT06000002"],
        )
        first = result.included_studies[0]
        self.assertEqual(first.program_name, "Example oncology programme")
        self.assertEqual(first.status, "ACTIVE_NOT_RECRUITING")
        self.assertEqual(first.phases, ("PHASE1",))
        self.assertEqual(
            [(item.intervention_type, item.name) for item in first.interventions],
            [("BIOLOGICAL", "Asset Alpha"), ("DRUG", "Standard of Care")],
        )
        self.assertEqual(first.sponsor.name, "Example Therapeutics")
        self.assertEqual(first.sponsor.agency_class, "INDUSTRY")
        self.assertEqual(first.start_date, "2024-08-09")
        self.assertEqual(first.primary_completion_date, "2026-09")
        self.assertEqual(first.completion_date, "2026-12")
        self.assertEqual(first.source_class, "clinical_trial_registry")
        self.assertEqual(
            first.source_locator,
            "https://clinicaltrials.gov/study/NCT06000001",
        )
        self.assertEqual(
            first.retrieved_at,
            datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )
        self.assertTrue(first.source_payload.startswith("{"))
        self.assertEqual(
            first.content_sha256,
            hashlib.sha256(first.source_payload.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            result.pages[0].content_sha256,
            hashlib.sha256(body).hexdigest(),
        )
        self.assertEqual(result.pages[0].source_payload, body.decode())
        self.assertEqual(
            transport.requests,
            [
                (
                    source_url,
                    {
                        "Accept": "application/json",
                    },
                )
            ],
        )

    def test_converts_registry_records_to_exact_clinical_evidence(self) -> None:
        body = (
            FIXTURE_ROOT / "clinical-trials-programme.json"
        ).read_bytes()
        snapshot = ClinicalTrialsCollector(
            ClinicalTrialsSettings(),
            transport=FixtureTransport({studies_url(): body}),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        ).collect(
            primary_source_request(),
            ClinicalTrialSearchIdentity(
                program_name="Example oncology programme",
                search_terms=("Asset Alpha", "Asset Beta"),
            ),
        )

        passages = clinical_trials_pipeline_inputs(snapshot)
        proof = clinical_trials_coverage_proof(snapshot)

        self.assertEqual(
            [item.reference_key for item in passages],
            [
                "clinical-trial:NCT06000001",
                "clinical-trial:NCT06000002",
            ],
        )
        self.assertTrue(
            all(item.source_class == "clinical" for item in passages)
        )
        self.assertEqual(
            passages[0].coverage_keys,
            frozenset({"authoritative_trial"}),
        )
        self.assertEqual(
            passages[0].canonical_url,
            "https://clinicaltrials.gov/study/NCT06000001",
        )
        self.assertEqual(
            hashlib.sha256(passages[0].passage_text.encode()).hexdigest(),
            passages[0].document_content_hash,
        )
        self.assertEqual(proof.policy_version, "clinical-trials-source-v2")
        self.assertEqual(
            proof.evidence_reference_keys,
            tuple(item.reference_key for item in passages),
        )

    def test_excludes_temporally_unsafe_records_with_explicit_reasons(
        self,
    ) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "clinical-trials-programme.json").read_text()
        )
        base = payload["studies"][0]
        cutoff_day = deepcopy(base)
        cutoff_day["protocolSection"]["identificationModule"]["nctId"] = (
            "NCT06000003"
        )
        cutoff_day["protocolSection"]["statusModule"][
            "studyFirstPostDateStruct"
        ]["date"] = "2026-05-06"
        after_cutoff = deepcopy(base)
        after_cutoff["protocolSection"]["identificationModule"]["nctId"] = (
            "NCT06000004"
        )
        after_cutoff["protocolSection"]["statusModule"][
            "lastUpdatePostDateStruct"
        ]["date"] = "2026-05-07"
        ambiguous = deepcopy(base)
        ambiguous["protocolSection"]["identificationModule"]["nctId"] = (
            "NCT06000005"
        )
        ambiguous["protocolSection"]["statusModule"][
            "lastUpdatePostDateStruct"
        ]["date"] = "2026-05-05T12:00:00"
        body = json.dumps(
            {"studies": [after_cutoff, ambiguous, cutoff_day], "totalCount": 3}
        ).encode()
        after_cutoff_nct = "NCT06000004"
        collector = ClinicalTrialsCollector(
            ClinicalTrialsSettings(),
            transport=FixtureTransport(
                {
                    studies_url(): body,
                    history_summary_url(after_cutoff_nct): json.dumps(
                        {
                            "study": after_cutoff,
                            "topics": [],
                            "history": {"changes": []},
                        }
                    ).encode(),
                }
            ),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        result = collector.collect(
            primary_source_request(),
            ClinicalTrialSearchIdentity(
                program_name="Example oncology programme",
                search_terms=("Asset Alpha", "Asset Beta"),
            ),
        )

        self.assertEqual(result.included_studies, ())
        self.assertEqual(
            [
                (
                    study.nct_id,
                    study.publication_reason_code,
                    study.update_reason_code,
                )
                for study in result.excluded_studies
            ],
            [
                (
                    "NCT06000003",
                    "publication_date_only_ambiguous_at_cutoff",
                    "update_date_only_before_cutoff",
                ),
                (
                    "NCT06000004",
                    "publication_date_only_before_cutoff",
                    "clinical_trial_no_version_valid_at_cutoff",
                ),
                (
                    "NCT06000005",
                    "publication_date_only_before_cutoff",
                    "update_timezone_unresolved",
                ),
            ],
        )
        self.assertEqual(result.coverage.status, "indeterminate")
        self.assertEqual(
            result.coverage.reason_codes,
            ("clinical_trials_temporal_metadata_indeterminate",),
        )

    def test_replays_latest_posted_history_version_at_cutoff(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "clinical-trials-programme.json").read_text()
        )
        current = payload["studies"][0]
        nct_id = current["protocolSection"]["identificationModule"]["nctId"]
        current["protocolSection"]["statusModule"][
            "lastUpdatePostDateStruct"
        ]["date"] = "2026-06-05"
        historical = deepcopy(current)
        historical["protocolSection"]["statusModule"][
            "lastUpdatePostDateStruct"
        ]["date"] = "2026-04-16"
        search_body = json.dumps(
            {"studies": [current], "totalCount": 1}
        ).encode()
        summary_body = json.dumps(
            {
                "study": current,
                "topics": [],
                "history": {
                    "changes": [
                        {
                            "version": 22,
                            "date": "2026-04-13",
                            "status": "RECRUITING",
                            "studyType": "INTERVENTIONAL",
                            "moduleLabels": [],
                            "lastUpdateSubmitQcDate": "2026-04-13",
                        },
                        {
                            "version": 23,
                            "date": "2026-06-03",
                            "status": "RECRUITING",
                            "studyType": "INTERVENTIONAL",
                            "moduleLabels": [],
                            "lastUpdateSubmitQcDate": "2026-06-03",
                        },
                    ]
                },
            }
        ).encode()
        version_body = json.dumps(
            {"study": historical, "studyVersion": 22}
        ).encode()
        transport = FixtureTransport(
            {
                studies_url(): search_body,
                history_summary_url(nct_id): summary_body,
                history_version_url(nct_id, 22): version_body,
            }
        )
        retrieval_times = iter(
            (
                datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
                datetime(2026, 5, 7, 1, 1, tzinfo=UTC),
            )
        )

        result = ClinicalTrialsCollector(
            ClinicalTrialsSettings(),
            transport=transport,
            clock=lambda: next(retrieval_times),
        ).collect(
            primary_source_request(),
            ClinicalTrialSearchIdentity(
                program_name="Example oncology programme",
                search_terms=("Asset Alpha", "Asset Beta"),
            ),
        )

        self.assertEqual(result.coverage.status, "covered")
        self.assertEqual(len(result.included_studies), 1)
        study = result.included_studies[0]
        self.assertEqual(study.history_version_index, 22)
        self.assertEqual(
            study.source_locator,
            history_version_url(nct_id, 22),
        )
        self.assertEqual(
            study.canonical_url,
            f"https://clinicaltrials.gov/study/{nct_id}",
        )
        self.assertEqual(study.last_update_post_date_raw, "2026-04-16")
        self.assertEqual(json.loads(study.source_payload)["studyVersion"], 22)
        self.assertEqual(
            [url for url, _headers in transport.requests],
            [
                studies_url(),
                history_summary_url(nct_id),
                history_version_url(nct_id, 22),
            ],
        )

    def test_history_version_wrapper_identity_must_match_request(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "clinical-trials-programme.json").read_text()
        )
        current = payload["studies"][0]
        nct_id = current["protocolSection"]["identificationModule"]["nctId"]
        current["protocolSection"]["statusModule"][
            "lastUpdatePostDateStruct"
        ]["date"] = "2026-06-05"
        summary = {
            "study": current,
            "topics": [],
            "history": {
                "changes": [
                    {
                        "version": 22,
                        "date": "2026-04-13",
                        "status": "RECRUITING",
                        "studyType": "INTERVENTIONAL",
                        "moduleLabels": [],
                        "lastUpdateSubmitQcDate": "2026-04-13",
                    }
                ]
            },
        }
        transport = FixtureTransport(
            {
                studies_url(): json.dumps(
                    {"studies": [current], "totalCount": 1}
                ).encode(),
                history_summary_url(nct_id): json.dumps(summary).encode(),
                history_version_url(nct_id, 22): json.dumps(
                    {"study": current, "studyVersion": 21}
                ).encode(),
            }
        )

        with self.assertRaisesRegex(
            ClinicalTrialsCollectorError,
            "history version identity mismatch",
        ):
            ClinicalTrialsCollector(
                ClinicalTrialsSettings(),
                transport=transport,
                clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
            ).collect(
                primary_source_request(),
                ClinicalTrialSearchIdentity(
                    program_name="Example oncology programme",
                    search_terms=("Asset Alpha", "Asset Beta"),
                ),
            )

    def test_collects_all_pages_and_deduplicates_by_nct_id(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "clinical-trials-programme.json").read_text()
        )
        first_study = payload["studies"][1]
        second_study = payload["studies"][0]
        first_body = json.dumps(
            {
                "studies": [first_study],
                "nextPageToken": "TOKEN_2",
                "totalCount": 2,
            }
        ).encode()
        second_body = json.dumps(
            {
                "studies": [second_study, first_study],
                "totalCount": 2,
            }
        ).encode()
        transport = FixtureTransport(
            {
                studies_url(): first_body,
                studies_url(page_token="TOKEN_2"): second_body,
            }
        )
        retrieval_times = iter(
            (
                datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
                datetime(2026, 5, 7, 1, 1, tzinfo=UTC),
            )
        )
        collector = ClinicalTrialsCollector(
            ClinicalTrialsSettings(),
            transport=transport,
            clock=lambda: next(retrieval_times),
        )

        result = collector.collect(
            primary_source_request(),
            ClinicalTrialSearchIdentity(
                program_name="Example oncology programme",
                search_terms=("Asset Alpha", "Asset Beta"),
            ),
        )

        self.assertEqual(
            [study.nct_id for study in result.included_studies],
            ["NCT06000001", "NCT06000002"],
        )
        self.assertEqual(
            [page.source_url for page in result.pages],
            [studies_url(), studies_url(page_token="TOKEN_2")],
        )
        self.assertEqual(
            [page.content_sha256 for page in result.pages],
            [
                hashlib.sha256(first_body).hexdigest(),
                hashlib.sha256(second_body).hexdigest(),
            ],
        )

    def test_missing_update_time_is_preserved_as_indeterminate(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "clinical-trials-programme.json").read_text()
        )
        study = payload["studies"][0]
        del study["protocolSection"]["statusModule"][
            "lastUpdatePostDateStruct"
        ]
        body = json.dumps({"studies": [study], "totalCount": 1}).encode()
        collector = ClinicalTrialsCollector(
            ClinicalTrialsSettings(),
            transport=FixtureTransport({studies_url(): body}),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        result = collector.collect(
            primary_source_request(),
            ClinicalTrialSearchIdentity(
                program_name="Example oncology programme",
                search_terms=("Asset Alpha", "Asset Beta"),
            ),
        )

        self.assertEqual(result.included_studies, ())
        self.assertEqual(len(result.excluded_studies), 1)
        self.assertIsNone(
            result.excluded_studies[0].last_update_post_date_raw
        )
        self.assertEqual(
            result.excluded_studies[0].update_reason_code,
            "update_time_unavailable",
        )
        self.assertEqual(result.coverage.status, "indeterminate")

    def test_malformed_intervention_fails_closed(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "clinical-trials-programme.json").read_text()
        )
        study = payload["studies"][0]
        study["protocolSection"]["armsInterventionsModule"][
            "interventions"
        ] = ["not-a-structured-intervention"]
        body = json.dumps({"studies": [study], "totalCount": 1}).encode()
        collector = ClinicalTrialsCollector(
            ClinicalTrialsSettings(),
            transport=FixtureTransport({studies_url(): body}),
        )

        with self.assertRaisesRegex(
            ClinicalTrialsCollectorError,
            "intervention is invalid",
        ):
            collector.collect(
                primary_source_request(),
                ClinicalTrialSearchIdentity(
                    program_name="Example oncology programme",
                    search_terms=("Asset Alpha", "Asset Beta"),
                ),
            )

    def test_unrelated_search_result_cannot_grant_programme_coverage(
        self,
    ) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "clinical-trials-programme.json").read_text()
        )
        unrelated = payload["studies"][0]
        identity = unrelated["protocolSection"]["identificationModule"]
        identity["briefTitle"] = "Unrelated metabolic study"
        identity["officialTitle"] = "Study of unrelated compound"
        interventions = unrelated["protocolSection"][
            "armsInterventionsModule"
        ]["interventions"]
        interventions[0]["name"] = "Unrelated Compound"
        body = json.dumps(
            {"studies": [unrelated], "totalCount": 1}
        ).encode()
        collector = ClinicalTrialsCollector(
            ClinicalTrialsSettings(),
            transport=FixtureTransport({studies_url(): body}),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        result = collector.collect(
            primary_source_request(),
            ClinicalTrialSearchIdentity(
                program_name="Example oncology programme",
                search_terms=("Asset Alpha", "Asset Beta"),
            ),
        )

        self.assertEqual(result.included_studies, ())
        self.assertFalse(result.excluded_studies[0].program_associated)
        self.assertEqual(
            result.excluded_studies[0].association_reason_code,
            "clinical_trial_program_alias_missing",
        )
        self.assertEqual(
            result.coverage.reason_codes,
            ("clinical_trials_program_association_missing",),
        )

    def test_matching_program_requires_issuer_or_declared_partner(
        self,
    ) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "clinical-trials-programme.json").read_text()
        )
        study = payload["studies"][0]
        sponsor = study["protocolSection"]["sponsorCollaboratorsModule"][
            "leadSponsor"
        ]
        sponsor["name"] = "Independent Research Partner"
        body = json.dumps({"studies": [study], "totalCount": 1}).encode()
        collector = ClinicalTrialsCollector(
            ClinicalTrialsSettings(),
            transport=FixtureTransport({studies_url(): body}),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        excluded = collector.collect(
            primary_source_request(),
            ClinicalTrialSearchIdentity(
                program_name="Example oncology programme",
                search_terms=("Asset Alpha", "Asset Beta"),
            ),
        )
        included = collector.collect(
            primary_source_request(),
            ClinicalTrialSearchIdentity(
                program_name="Example oncology programme",
                search_terms=("Asset Alpha", "Asset Beta"),
                allowed_sponsor_names=("Independent Research Partner",),
            ),
        )

        self.assertEqual(excluded.included_studies, ())
        self.assertTrue(excluded.excluded_studies[0].program_associated)
        self.assertFalse(excluded.excluded_studies[0].issuer_associated)
        self.assertEqual(
            excluded.excluded_studies[0].association_reason_code,
            "clinical_trial_issuer_association_missing",
        )
        self.assertEqual(
            [study.nct_id for study in included.included_studies],
            [study["protocolSection"]["identificationModule"]["nctId"]],
        )

    def test_after_cutoff_records_report_historical_coverage_gap(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "clinical-trials-programme.json").read_text()
        )
        study = payload["studies"][0]
        study["protocolSection"]["statusModule"][
            "studyFirstPostDateStruct"
        ]["date"] = "2026-05-07"
        body = json.dumps({"studies": [study], "totalCount": 1}).encode()
        collector = ClinicalTrialsCollector(
            ClinicalTrialsSettings(),
            transport=FixtureTransport({studies_url(): body}),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        result = collector.collect(
            primary_source_request(),
            ClinicalTrialSearchIdentity(
                program_name="Example oncology programme",
                search_terms=("Asset Alpha", "Asset Beta"),
            ),
        )

        self.assertEqual(result.coverage.status, "not_covered")
        self.assertEqual(
            result.coverage.reason_codes,
            ("clinical_trials_no_study_valid_at_cutoff",),
        )
        self.assertEqual(
            result.excluded_studies[0].publication_reason_code,
            "publication_after_cutoff",
        )

    def test_valid_study_cannot_hide_indeterminate_matching_study(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "clinical-trials-programme.json").read_text()
        )
        payload["studies"][0]["protocolSection"]["statusModule"][
            "lastUpdatePostDateStruct"
        ]["date"] = "2026-05-05T12:00:00"
        body = json.dumps(payload).encode()
        collector = ClinicalTrialsCollector(
            ClinicalTrialsSettings(),
            transport=FixtureTransport({studies_url(): body}),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        result = collector.collect(
            primary_source_request(),
            ClinicalTrialSearchIdentity(
                program_name="Example oncology programme",
                search_terms=("Asset Alpha", "Asset Beta"),
            ),
        )

        self.assertEqual(len(result.included_studies), 1)
        self.assertEqual(len(result.excluded_studies), 1)
        self.assertEqual(result.coverage.status, "indeterminate")
        self.assertEqual(
            result.coverage.reason_codes,
            ("clinical_trials_temporal_metadata_indeterminate",),
        )


if __name__ == "__main__":
    unittest.main()
