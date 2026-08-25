from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile
import unittest
from http.client import HTTPConnection
from urllib.parse import urlsplit

from tests.test_primary_source_captures import archive_bytes, capture_value
from tests.test_primary_source_plans import CUTOFF, OPERATOR_ID, SECURITY_ID
from workers.desktop.control import DesktopControlServer
from workers.desktop.research_capture_import import DesktopCaptureImportService
from workers.primary_sources.storage import FilePrimarySourceCaptureRepository


def _archive_path(directory: Path) -> Path:
    value, payloads, source_plan = capture_value()
    path = directory / "capture.zip"
    path.write_bytes(archive_bytes(value, payloads, source_plan))
    return path


def _import_body(archive_path: Path, **overrides) -> dict:
    defaults = {
        "operator_id": OPERATOR_ID,
        "security_id": SECURITY_ID,
        "cik": "0001601830",
        "issuer_name": "Recursion Pharmaceuticals, Inc.",
        "primary_listing_exchange": "NASDAQ",
        "as_of_cutoff": CUTOFF.isoformat(),
        "archive_path": str(archive_path),
        "trusted_issuer_hosts": ["ir.recursion.com"],
    }
    defaults.update(overrides)
    return defaults


class DesktopResearchCaptureImportLoopbackTests(unittest.TestCase):
    def test_loopback_requires_bearer_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "captures"
            server = DesktopControlServer(
                service=object(),  # type: ignore[arg-type]
                control_token="control-secret",
                research_capture_import_service=DesktopCaptureImportService(
                    FilePrimarySourceCaptureRepository(root),
                    clock=lambda: datetime(2026, 5, 7, 3, tzinfo=UTC),
                ),
            )
            server.start()
            self.addCleanup(server.stop)
            parsed = urlsplit(server.origin)
            connection = HTTPConnection(parsed.hostname, parsed.port, timeout=1)
            connection.request(
                "POST",
                "/v1/research/captures/import",
                body=json.dumps(_import_body(_archive_path(Path(directory)))),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 401)
            response.read()

    def test_loopback_imports_valid_archive_and_returns_sanitized_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "captures"
            server = DesktopControlServer(
                service=object(),  # type: ignore[arg-type]
                control_token="control-secret",
                research_capture_import_service=DesktopCaptureImportService(
                    FilePrimarySourceCaptureRepository(root),
                    clock=lambda: datetime(2026, 5, 7, 3, tzinfo=UTC),
                ),
            )
            server.start()
            self.addCleanup(server.stop)
            parsed = urlsplit(server.origin)
            connection = HTTPConnection(parsed.hostname, parsed.port, timeout=1)
            archive_path = _archive_path(Path(directory))
            connection.request(
                "POST",
                "/v1/research/captures/import",
                body=json.dumps(_import_body(archive_path)),
                headers={
                    "Authorization": "Bearer control-secret",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read())
            self.assertEqual(
                payload["contract_version"], "primary_source_capture_import_receipt.v1"
            )
            serialized = json.dumps(payload)
            for prohibited in ("archive", "path", "package_sha256", "plan_content_hash"):
                self.assertNotIn(prohibited, serialized)

    def test_loopback_upload_accepts_raw_archive_and_returns_sanitized_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "captures"
            server = DesktopControlServer(
                service=object(),  # type: ignore[arg-type]
                control_token="control-secret",
                research_capture_import_service=DesktopCaptureImportService(
                    FilePrimarySourceCaptureRepository(root),
                    clock=lambda: datetime(2026, 5, 7, 3, tzinfo=UTC),
                ),
            )
            server.start()
            self.addCleanup(server.stop)
            parsed = urlsplit(server.origin)
            connection = HTTPConnection(parsed.hostname, parsed.port, timeout=1)
            raw_archive = Path(_archive_path(Path(directory))).read_bytes()
            connection.request(
                "POST",
                "/v1/research/captures/upload",
                body=raw_archive,
                headers={
                    "Authorization": "Bearer control-secret",
                    "Content-Type": "application/zip",
                    "X-IROS-Operator-ID": OPERATOR_ID,
                    "X-IROS-Security-ID": SECURITY_ID,
                    "X-IROS-CIK": "0001601830",
                    "X-IROS-Issuer-Name": "Recursion Pharmaceuticals, Inc.",
                    "X-IROS-Primary-Listing-Exchange": "NASDAQ",
                    "X-IROS-Confirm-Embedded-Issuer-Hosts": "true",
                },
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read())
            self.assertEqual(
                payload["contract_version"],
                "primary_source_capture_import_receipt.v1",
            )
            self.assertNotIn("package_sha256", json.dumps(payload))

    def test_loopback_rejects_malformed_request_and_unavailable_service(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "captures"
            server = DesktopControlServer(
                service=object(),  # type: ignore[arg-type]
                control_token="control-secret",
                research_capture_import_service=DesktopCaptureImportService(
                    FilePrimarySourceCaptureRepository(root),
                    clock=lambda: datetime(2026, 5, 7, 3, tzinfo=UTC),
                ),
            )
            server.start()
            self.addCleanup(server.stop)
            parsed = urlsplit(server.origin)
            connection = HTTPConnection(parsed.hostname, parsed.port, timeout=1)

            connection.request(
                "POST",
                "/v1/research/captures/import",
                body=json.dumps({"operator_id": OPERATOR_ID}),
                headers={
                    "Authorization": "Bearer control-secret",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()

            unavailable_server = DesktopControlServer(
                service=object(),  # type: ignore[arg-type]
                control_token="control-secret",
            )
            unavailable_server.start()
            self.addCleanup(unavailable_server.stop)
            parsed = urlsplit(unavailable_server.origin)
            connection = HTTPConnection(parsed.hostname, parsed.port, timeout=1)
            connection.request(
                "POST",
                "/v1/research/captures/import",
                body=json.dumps(_import_body(_archive_path(Path(directory)))),
                headers={
                    "Authorization": "Bearer control-secret",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 503)
            response.read()


if __name__ == "__main__":
    unittest.main()
