from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from workers.primary_sources.__main__ import run
from workers.primary_sources.acquisition import PrimarySourceAcquisitionResult


OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
SECURITY_ID = "a657d245-6bda-5476-930a-911667ea6c64"


def source_plan() -> bytes:
    return json.dumps(
        {
            "contract_version": "primary_source_plan.v3",
            "plan_id": "f1b00477-fd34-5e00-82fe-b49242915511",
            "revision": 3,
            "effective_at": "2026-05-06T23:59:59Z",
            "question_type": ("biotech_moonshot_catalyst_personal_research_assessment"),
            "workflow_config_version": (
                "biotech-moonshot-catalyst-personal-research-v1"
            ),
            "security": {
                "security_id": SECURITY_ID,
                "cik": "0001601830",
                "issuer_name": "Recursion Pharmaceuticals, Inc.",
                "primary_listing_exchange": "NASDAQ",
            },
            "sec_passages": [
                {
                    "reference_key": "sec-required",
                    "role": "required_filing",
                    "selected_form": "10-Q",
                    "selected_accession_number": "0001601830-26-000078",
                    "exact_text": "Quarterly report",
                },
                {
                    "reference_key": "sec-identity",
                    "role": "identity_listing",
                    "selected_form": "10-Q",
                    "selected_accession_number": "0001601830-26-000078",
                    "exact_text": "Class A Common Stock RXRX Nasdaq",
                },
                {
                    "reference_key": "financing:basic_shares",
                    "role": "financing",
                    "selected_form": "10-Q",
                    "selected_accession_number": "0001601830-26-000078",
                    "exact_text": "Common shares outstanding",
                },
                {
                    "reference_key": "corporate-action:basis-reconciliation",
                    "role": "corporate_action",
                    "selected_form": "10-Q",
                    "selected_accession_number": "0001601830-26-000078",
                    "exact_text": "Comparative share basis",
                },
            ],
            "issuer_sources": [
                {
                    "source_key": "issuer-program",
                    "requirement_id": "issuer_pipeline",
                    "title": "Issuer program",
                    "source_url": "https://ir.example.com/program",
                    "publication_time": "2026-05-06T10:30:00Z",
                    "effective_date": "2026-05-06",
                    "coverage_role": "required",
                    "coverage_mode": "all",
                    "passages": [
                        {
                            "passage_key": "program",
                            "locator": "Program",
                            "exact_text": "Active therapeutic program",
                        }
                    ],
                }
            ],
            "clinical_trial_search": {
                "program_name": "REC-4881",
                "search_terms": ["REC-4881"],
                "allowed_sponsor_names": ["Recursion Pharmaceuticals"],
            },
            "regulatory_sources": [
                {
                    "source_key": "fda-record",
                    "requirement_id": "us_regulatory",
                    "title": "FDA record",
                    "source_url": "https://www.fda.gov/record",
                    "publication_time": "2026-01-01T00:00:00Z",
                    "effective_date": "2026-01-01",
                    "coverage_role": "required",
                    "coverage_mode": "all",
                    "passages": [
                        {
                            "passage_key": "record",
                            "locator": "Record",
                            "exact_text": "FDA evidence",
                        }
                    ],
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


class PrimarySourceCliTests(unittest.TestCase):
    def test_acquire_derives_exact_request_from_plan_and_writes_archive(self) -> None:
        calls = []

        def acquire(**kwargs):
            calls.append(kwargs)
            return PrimarySourceAcquisitionResult(
                archive=b"immutable-capture",
                selected_accessions=("0001601830-26-000078",),
                issuer_source_count=1,
                clinical_study_count=1,
                regulatory_source_count=1,
                companyfact_count=4,
            )

        with TemporaryDirectory() as directory:
            plan_path = Path(directory) / "plan.json"
            output_path = Path(directory) / "capture.zip"
            plan_path.write_bytes(source_plan())

            exit_code = run(
                [
                    "acquire",
                    "--plan",
                    str(plan_path),
                    "--ticker",
                    "RXRX",
                    "--operator-id",
                    OPERATOR_ID,
                    "--capture-id",
                    "68477247-a8fe-5e7d-977a-7005f91177fc",
                    "--revision",
                    "3",
                    "--trusted-issuer-host",
                    "ir.example.com",
                    "--output",
                    str(output_path),
                ],
                environ={
                    "SEC_USER_AGENT": ("Investment Research OS operator@example.com")
                },
                acquire=acquire,
                clock=lambda: datetime(2026, 8, 4, 4, 0, tzinfo=UTC),
                transport=object(),
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(output_path.read_bytes(), b"immutable-capture")
            self.assertEqual(len(calls), 1)
            call = calls[0]
            self.assertEqual(call["ticker"], "RXRX")
            self.assertEqual(call["revision"], 3)
            self.assertEqual(
                call["request"].as_of_cutoff,
                datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC),
            )
            self.assertEqual(call["request"].security_id, SECURITY_ID)
            self.assertEqual(call["request"].operator_id, OPERATOR_ID)
            self.assertEqual(
                call["user_agent"],
                "Investment Research OS operator@example.com",
            )
            self.assertIsNone(call["assembled_at"])

    def test_acquire_refuses_to_overwrite_different_capture_bytes(self) -> None:
        def acquire(**kwargs):
            del kwargs
            return PrimarySourceAcquisitionResult(
                archive=b"new-capture",
                selected_accessions=(),
                issuer_source_count=0,
                clinical_study_count=0,
                regulatory_source_count=0,
                companyfact_count=0,
            )

        with TemporaryDirectory() as directory:
            plan_path = Path(directory) / "plan.json"
            output_path = Path(directory) / "capture.zip"
            plan_path.write_bytes(source_plan())
            output_path.write_bytes(b"existing-capture")

            with self.assertRaisesRegex(
                RuntimeError,
                "already contains other bytes",
            ):
                run(
                    [
                        "acquire",
                        "--plan",
                        str(plan_path),
                        "--ticker",
                        "RXRX",
                        "--operator-id",
                        OPERATOR_ID,
                        "--capture-id",
                        "68477247-a8fe-5e7d-977a-7005f91177fc",
                        "--revision",
                        "3",
                        "--trusted-issuer-host",
                        "ir.example.com",
                        "--output",
                        str(output_path),
                    ],
                    environ={
                        "SEC_USER_AGENT": (
                            "Investment Research OS operator@example.com"
                        )
                    },
                    acquire=acquire,
                    clock=lambda: datetime(2026, 8, 4, 4, 0, tzinfo=UTC),
                    transport=object(),
                )

            self.assertEqual(output_path.read_bytes(), b"existing-capture")


if __name__ == "__main__":
    unittest.main()
