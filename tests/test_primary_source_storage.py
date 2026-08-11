from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from tests.test_primary_source_captures import (
    archive_bytes,
    capture_value,
    request,
)
from tests.test_primary_source_plans import research_run
from workers.primary_sources.captures import load_primary_source_capture
from workers.primary_sources.storage import (
    FilePrimarySourceCaptureRepository,
    PrimarySourceStorageError,
)


class PrimarySourceCaptureStorageTests(unittest.TestCase):
    def test_capture_cannot_bind_to_different_research_identity(self) -> None:
        value, payloads, source_plan = capture_value()
        archive = archive_bytes(value, payloads, source_plan)
        capture = load_primary_source_capture(
            archive,
            request=request(),
            trusted_issuer_hosts=("ir.recursion.com",),
            accepted_at=lambda: datetime(2026, 5, 7, 3, tzinfo=UTC),
        )

        with tempfile.TemporaryDirectory() as directory:
            repository = FilePrimarySourceCaptureRepository(Path(directory))
            persisted = repository.save_capture(capture, archive)

            with self.assertRaisesRegex(
                PrimarySourceStorageError,
                "does not match",
            ):
                repository.bind_to_run(
                    persisted,
                    replace(
                        research_run(),
                        security_id=("11111111-1111-4111-8111-111111111111"),
                    ),
                    evidence_policy_version="biotech-primary-evidence-v2",
                    bound_at=datetime(2026, 5, 7, 4, tzinfo=UTC),
                )

    def test_capture_binding_to_research_run_survives_restart(self) -> None:
        value, payloads, source_plan = capture_value()
        archive = archive_bytes(value, payloads, source_plan)
        capture = load_primary_source_capture(
            archive,
            request=request(),
            trusted_issuer_hosts=("ir.recursion.com",),
            accepted_at=lambda: datetime(2026, 5, 7, 3, tzinfo=UTC),
        )
        run = research_run()

        with tempfile.TemporaryDirectory() as directory:
            repository = FilePrimarySourceCaptureRepository(Path(directory))
            persisted = repository.save_capture(capture, archive)
            binding = repository.bind_to_run(
                persisted,
                run,
                evidence_policy_version="biotech-primary-evidence-v2",
                bound_at=datetime(2026, 5, 7, 4, tzinfo=UTC),
            )
            restarted = FilePrimarySourceCaptureRepository(Path(directory))

            restored = restarted.get_for_run(
                run.operator_id,
                run.id,
            )

        self.assertEqual(restored, binding)
        self.assertEqual(binding.capture_id, capture.capture_id)
        self.assertEqual(binding.plan_content_hash, capture.plan.content_hash)
        self.assertEqual(
            binding.evidence_policy_version,
            "biotech-primary-evidence-v2",
        )

    def test_corrupt_archive_is_rejected_after_restart(self) -> None:
        value, payloads, source_plan = capture_value()
        archive = archive_bytes(value, payloads, source_plan)
        capture = load_primary_source_capture(
            archive,
            request=request(),
            trusted_issuer_hosts=("ir.recursion.com",),
            accepted_at=lambda: datetime(2026, 5, 7, 3, tzinfo=UTC),
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = FilePrimarySourceCaptureRepository(root)
            repository.save_capture(capture, archive)
            stored_archive = (
                root
                / capture.plan.operator_id
                / capture.capture_id
                / str(capture.revision)
                / "capture.zip"
            )
            stored_archive.write_bytes(b"corrupt")
            restarted = FilePrimarySourceCaptureRepository(root)

            with self.assertRaisesRegex(
                PrimarySourceStorageError,
                "integrity mismatch",
            ):
                restarted.read_archive(
                    capture.plan.operator_id,
                    capture.capture_id,
                    capture.revision,
                )

    def test_identical_capture_retry_reuses_immutable_artifact(self) -> None:
        value, payloads, source_plan = capture_value()
        archive = archive_bytes(value, payloads, source_plan)
        capture = load_primary_source_capture(
            archive,
            request=request(),
            trusted_issuer_hosts=("ir.recursion.com",),
            accepted_at=lambda: datetime(2026, 5, 7, 3, tzinfo=UTC),
        )

        with tempfile.TemporaryDirectory() as directory:
            repository = FilePrimarySourceCaptureRepository(Path(directory))
            first = repository.save_capture(capture, archive)
            second = repository.save_capture(capture, archive)

        self.assertEqual(second, first)

    def test_capture_survives_repository_restart_and_revalidates(self) -> None:
        value, payloads, source_plan = capture_value()
        archive = archive_bytes(value, payloads, source_plan)
        source_request = request()
        capture = load_primary_source_capture(
            archive,
            request=source_request,
            trusted_issuer_hosts=("ir.recursion.com",),
            accepted_at=lambda: datetime(2026, 5, 7, 3, tzinfo=UTC),
        )

        with tempfile.TemporaryDirectory() as directory:
            first = FilePrimarySourceCaptureRepository(Path(directory))
            persisted = first.save_capture(capture, archive)
            restarted = FilePrimarySourceCaptureRepository(Path(directory))

            restored = restarted.load_capture(
                source_request,
                capture.capture_id,
                capture.revision,
                trusted_issuer_hosts=("ir.recursion.com",),
            )

        self.assertEqual(restored, capture)
        self.assertEqual(persisted.package_sha256, capture.receipt.package_sha256)
        self.assertEqual(persisted.byte_length, len(archive))
        self.assertEqual(
            persisted.capture_content_hash,
            capture.content_hash,
        )


if __name__ == "__main__":
    unittest.main()
