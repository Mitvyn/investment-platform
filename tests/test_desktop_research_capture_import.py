from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest

from tests.test_primary_source_captures import archive_bytes, capture_value
from tests.test_primary_source_plans import CUTOFF, OPERATOR_ID, SECURITY_ID
from workers.desktop.research import DesktopResearchCaptureCatalog
from workers.desktop.research_capture_import import (
    DesktopCaptureImportError,
    DesktopCaptureImportRequest,
    DesktopCaptureImportService,
)
from workers.primary_sources.storage import FilePrimarySourceCaptureRepository

OTHER_SECURITY_ID = "44444444-4444-4444-8444-444444444444"


def _valid_archive_bytes() -> bytes:
    value, payloads, source_plan = capture_value()
    return archive_bytes(value, payloads, source_plan)


def _write_archive(directory: Path, data: bytes, name: str = "capture.zip") -> Path:
    path = directory / name
    path.write_bytes(data)
    return path


class DesktopCaptureImportServiceTests(unittest.TestCase):
    def _service(self, root: Path) -> DesktopCaptureImportService:
        return DesktopCaptureImportService(
            FilePrimarySourceCaptureRepository(root),
            clock=lambda: datetime(2026, 5, 7, 3, tzinfo=UTC),
        )

    def _request(self, archive_path: Path, **overrides) -> DesktopCaptureImportRequest:
        defaults = dict(
            operator_id=OPERATOR_ID,
            security_id=SECURITY_ID,
            cik="0001601830",
            issuer_name="Recursion Pharmaceuticals, Inc.",
            primary_listing_exchange="NASDAQ",
            as_of_cutoff=CUTOFF,
            archive_path=archive_path,
            trusted_issuer_hosts=("ir.recursion.com",),
        )
        defaults.update(overrides)
        return DesktopCaptureImportRequest(**defaults)

    def test_imports_valid_local_archive_and_makes_it_selectable_in_launcher_catalog(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "captures"
            archive_path = _write_archive(Path(directory), _valid_archive_bytes())
            service = self._service(root)

            persisted = service.import_capture(self._request(archive_path))

            self.assertEqual(persisted.operator_id, OPERATOR_ID)
            self.assertEqual(persisted.security_id, SECURITY_ID)

            catalog = DesktopResearchCaptureCatalog(
                FilePrimarySourceCaptureRepository(root)
            )
            result = catalog.list_captures(
                operator_id=OPERATOR_ID, security_id=SECURITY_ID
            )
            self.assertEqual(result.capture_count, 1)
            self.assertEqual(
                result.captures[0].capture_content_hash,
                persisted.capture_content_hash,
            )

    def test_import_survives_restart_and_repeated_identical_import_is_idempotent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "captures"
            archive_path = _write_archive(Path(directory), _valid_archive_bytes())
            service = self._service(root)
            first = service.import_capture(self._request(archive_path))

            reopened_service = self._service(root)
            second = reopened_service.import_capture(self._request(archive_path))

            self.assertEqual(first.capture_content_hash, second.capture_content_hash)
            self.assertEqual(first.accepted_at, second.accepted_at)

    def test_rejects_relative_symlink_missing_oversized_or_empty_archive_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "captures"
            service = self._service(root)
            valid_bytes = _valid_archive_bytes()

            real_archive = _write_archive(Path(directory), valid_bytes, "real.zip")
            symlink_path = Path(directory) / "linked.zip"
            symlink_path.symlink_to(real_archive)
            empty_path = _write_archive(Path(directory), b"", "empty.zip")
            missing_path = Path(directory) / "missing.zip"

            with self.assertRaises(DesktopCaptureImportError):
                service.import_capture(
                    self._request(Path("relative.zip"))
                )
            with self.assertRaises(DesktopCaptureImportError):
                service.import_capture(self._request(symlink_path))
            with self.assertRaises(DesktopCaptureImportError):
                service.import_capture(self._request(empty_path))
            with self.assertRaises(DesktopCaptureImportError):
                service.import_capture(self._request(missing_path))

    def test_rejects_archive_that_fails_plan_or_identity_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "captures"
            service = self._service(root)
            value, payloads, source_plan = capture_value()
            mismatched = dict(value)
            mismatched["context"] = {**value["context"], "security_id": OTHER_SECURITY_ID}
            bad_archive = archive_bytes(mismatched, payloads, source_plan)
            archive_path = _write_archive(Path(directory), bad_archive)

            with self.assertRaises(DesktopCaptureImportError):
                service.import_capture(self._request(archive_path))

    def test_rejects_missing_trusted_issuer_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "captures"
            service = self._service(root)
            archive_path = _write_archive(Path(directory), _valid_archive_bytes())

            with self.assertRaises(DesktopCaptureImportError):
                service.import_capture(
                    self._request(archive_path, trusted_issuer_hosts=())
                )

    def test_conflicting_archive_bytes_for_same_identity_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "captures"
            service = self._service(root)
            archive_path = _write_archive(Path(directory), _valid_archive_bytes())
            service.import_capture(self._request(archive_path))

            value, payloads, source_plan = capture_value()
            conflicting_value = dict(value)
            conflicting_value["assembled_at"] = datetime(
                2026, 5, 7, 5, tzinfo=UTC
            ).isoformat()
            conflicting_archive = archive_bytes(conflicting_value, payloads, source_plan)
            conflicting_path = _write_archive(
                Path(directory), conflicting_archive, "conflict.zip"
            )

            with self.assertRaises(DesktopCaptureImportError):
                service.import_capture(self._request(conflicting_path))


if __name__ == "__main__":
    unittest.main()
