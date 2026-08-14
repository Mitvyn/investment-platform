from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile
import unittest

from workers.desktop.research import DesktopResearchCaptureCatalog
from workers.primary_sources.storage import (
    FilePrimarySourceCaptureRepository,
    PrimarySourceStorageError,
)


OPERATOR_ID = "11111111-1111-4111-8111-111111111111"
OTHER_OPERATOR_ID = "22222222-2222-4222-8222-222222222222"
SECURITY_ID = "33333333-3333-4333-8333-333333333333"
OTHER_SECURITY_ID = "44444444-4444-4444-8444-444444444444"
CUTOFF = datetime(2026, 5, 6, 23, 59, tzinfo=UTC)
QUESTION_VERSION = "biotech_moonshot_catalyst_personal_research_assessment.v1"
WORKFLOW_VERSION = "biotech-moonshot-catalyst-personal-research-v1"


class DesktopResearchCaptureCatalogTests(unittest.TestCase):
    def test_catalog_returns_bounded_exact_context_in_deterministic_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_metadata(
                root,
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                capture_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                revision=1,
                accepted_at="2026-05-07T01:00:00+00:00",
            )
            _write_metadata(
                root,
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                capture_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                revision=2,
                accepted_at="2026-05-07T03:00:00+00:00",
            )
            _write_metadata(
                root,
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                capture_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                revision=1,
                accepted_at="2026-05-07T02:00:00+00:00",
            )
            _write_metadata(
                root,
                operator_id=OPERATOR_ID,
                security_id=OTHER_SECURITY_ID,
                capture_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                revision=1,
                accepted_at="2026-05-07T04:00:00+00:00",
            )
            _write_metadata(
                root,
                operator_id=OTHER_OPERATOR_ID,
                security_id=SECURITY_ID,
                capture_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
                revision=1,
                accepted_at="2026-05-07T05:00:00+00:00",
            )
            catalog = DesktopResearchCaptureCatalog(
                FilePrimarySourceCaptureRepository(root)
            )

            result = catalog.list_captures(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                question_type_version=QUESTION_VERSION,
                workflow_config_version=WORKFLOW_VERSION,
                as_of_cutoff=CUTOFF,
                max_count=2,
            )

        self.assertEqual(result.capture_count, 2)
        self.assertEqual(
            [entry.capture_id for entry in result.captures],
            [
                "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            ],
        )

    def test_catalog_serialization_exposes_receipt_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_metadata(
                root,
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                capture_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                revision=1,
                accepted_at="2026-05-07T01:00:00+00:00",
            )
            catalog = DesktopResearchCaptureCatalog(
                FilePrimarySourceCaptureRepository(root)
            )

            payload = catalog.list_captures(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
            ).as_dict()

        self.assertEqual(payload["capture_count"], 1)
        self.assertEqual(
            payload["contract_version"],
            "accepted_research_capture_list.v1",
        )
        self.assertEqual(
            set(payload),
            {"capture_count", "captures", "contract_version"},
        )
        self.assertEqual(
            set(payload["captures"][0]),
            {
                "accepted_at",
                "as_of_cutoff",
                "capture_content_hash",
                "capture_id",
                "capture_revision",
                "question_type",
                "question_type_version",
                "workflow_config_version",
            },
        )
        serialized = json.dumps(payload)
        for prohibited in (
            "archive",
            "path",
            "payload",
            "package_sha256",
            "plan_content_hash",
        ):
            self.assertNotIn(prohibited, serialized)

    def test_catalog_ignores_in_progress_atomic_capture_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
            _write_metadata(
                root,
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                capture_id=capture_id,
                revision=1,
                accepted_at="2026-05-07T01:00:00+00:00",
            )
            (root / OPERATOR_ID / capture_id / ".2.in-progress").mkdir()
            catalog = DesktopResearchCaptureCatalog(
                FilePrimarySourceCaptureRepository(root)
            )

            result = catalog.list_captures(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
            )

        self.assertEqual(result.capture_count, 1)
        self.assertEqual(result.captures[0].capture_revision, 1)

    def test_catalog_rejects_unbounded_or_invalid_queries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = DesktopResearchCaptureCatalog(
                FilePrimarySourceCaptureRepository(Path(directory))
            )

            for max_count in (False, 0, 101):
                with (
                    self.subTest(max_count=max_count),
                    self.assertRaises(PrimarySourceStorageError),
                ):
                    catalog.list_captures(
                        operator_id=OPERATOR_ID,
                        security_id=SECURITY_ID,
                        max_count=max_count,
                    )
            with self.assertRaises(PrimarySourceStorageError):
                catalog.list_captures(
                    operator_id=OPERATOR_ID,
                    security_id="not-a-uuid",
                )

    def test_catalog_rejects_noncanonical_revision_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_metadata(
                root,
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                capture_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                revision=1,
                accepted_at="2026-05-07T01:00:00+00:00",
            )
            revision = root / OPERATOR_ID / "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" / "1"
            revision.rename(revision.with_name("01"))
            catalog = DesktopResearchCaptureCatalog(
                FilePrimarySourceCaptureRepository(root)
            )

            with self.assertRaisesRegex(
                PrimarySourceStorageError,
                "capture revision is invalid",
            ):
                catalog.list_captures(
                    operator_id=OPERATOR_ID,
                    security_id=SECURITY_ID,
                )


def _write_metadata(
    root: Path,
    *,
    operator_id: str,
    security_id: str,
    capture_id: str,
    revision: int,
    accepted_at: str,
) -> None:
    target = root / operator_id / capture_id / str(revision)
    target.mkdir(parents=True)
    payload = {
        "contract_version": "primary_source_capture_storage.v1",
        "operator_id": operator_id,
        "security_id": security_id,
        "as_of_cutoff": CUTOFF.isoformat(),
        "capture_id": capture_id,
        "capture_revision": revision,
        "plan_id": "55555555-5555-4555-8555-555555555555",
        "plan_revision": 1,
        "plan_content_hash": "1" * 64,
        "question_type": "biotech_moonshot_catalyst_personal_research_assessment",
        "question_type_version": QUESTION_VERSION,
        "workflow_config_version": WORKFLOW_VERSION,
        "thesis_contract_id": "biotech_moonshot_catalyst_personal_research_v1",
        "eligibility_policy_version": "biotech-security-eligibility-v1",
        "package_sha256": "2" * 64,
        "capture_content_hash": "3" * 64,
        "byte_length": 123,
        "assembled_at": "2026-05-07T00:00:00+00:00",
        "accepted_at": accepted_at,
        "loader_version": "primary-source-capture-loader-v1",
        "provenance_mode": "operator_supplied_unverified",
    }
    (target / "metadata.json").write_text(json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
