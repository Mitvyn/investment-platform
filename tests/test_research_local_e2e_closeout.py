"""IRO-045/IRO-046/IRO-069 closeout: proves the full local, offline path

    accepted-capture archive import
    -> immutable acceptance receipt
    -> security-scoped explicit selection
    -> survives desktop restart

for one canonical security, through the real authenticated desktop loopback
(no mocked fetch), and proves it never leaks across security identity.

This does not duplicate the existing per-behavior tests in
`test_desktop_research_capture_import.py` / `..._loopback.py`; it closes the
one gap those files do not cover: that the accepted-capture selector is
scoped to the exact requested `security_id` and excludes an authenticated
operator's captures for every other security, proven over one real HTTP
loopback server rather than by calling the catalog object directly.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlsplit

from tests.test_primary_source_captures import archive_bytes, capture_value
from tests.test_primary_source_plans import CUTOFF, OPERATOR_ID, SECURITY_ID
from workers.desktop.control import DesktopControlServer
from workers.desktop.research import DesktopResearchCaptureCatalog
from workers.desktop.research_capture_import import DesktopCaptureImportService
from workers.primary_sources.storage import FilePrimarySourceCaptureRepository

FOREIGN_SECURITY_ID = "99999999-9999-4999-8999-999999999999"


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


def _build_server(root: Path) -> DesktopControlServer:
    repository = FilePrimarySourceCaptureRepository(root)
    return DesktopControlServer(
        service=object(),  # type: ignore[arg-type]
        control_token="control-secret",
        research_capture_catalog=DesktopResearchCaptureCatalog(repository),
        research_capture_import_service=DesktopCaptureImportService(
            repository,
            clock=lambda: datetime(2026, 5, 7, 3, tzinfo=UTC),
        ),
    )


def _get_json(connection: HTTPConnection, path: str) -> tuple[int, dict]:
    connection.request(
        "GET", path, headers={"Authorization": "Bearer control-secret"}
    )
    response = connection.getresponse()
    return response.status, json.loads(response.read())


def _post_json(connection: HTTPConnection, path: str, body: dict) -> tuple[int, dict]:
    connection.request(
        "POST",
        path,
        body=json.dumps(body),
        headers={
            "Authorization": "Bearer control-secret",
            "Content-Type": "application/json",
        },
    )
    response = connection.getresponse()
    return response.status, json.loads(response.read())


class ResearchLocalEndToEndCloseoutTests(unittest.TestCase):
    def test_full_local_path_is_security_scoped_and_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "captures"
            archive_path = _archive_path(Path(directory))
            server = _build_server(root)
            server.start()
            self.addCleanup(server.stop)
            parsed = urlsplit(server.origin)
            connection = HTTPConnection(parsed.hostname, parsed.port, timeout=2)

            # 1. Explicit accepted-capture archive import -> immutable receipt.
            status, receipt = _post_json(
                connection,
                "/v1/research/captures/import",
                _import_body(archive_path),
            )
            self.assertEqual(status, 200)
            self.assertEqual(
                receipt["contract_version"], "primary_source_capture_import_receipt.v1"
            )
            capture_id = receipt["capture_id"]
            capture_revision = receipt["capture_revision"]
            capture_content_hash = receipt["capture_content_hash"]

            # Never leaks archive bytes, filesystem path, or a package hash.
            raw = json.dumps(receipt)
            for forbidden in (
                str(archive_path),
                "archive_path",
                "package_sha256",
                "plan_content_hash",
                "control-secret",
            ):
                self.assertNotIn(forbidden, raw)

            # 2. Explicit selector: scoped to the exact requested security only.
            status, own_list = _get_json(
                connection,
                f"/v1/research/captures?operator_id={OPERATOR_ID}&security_id={SECURITY_ID}",
            )
            self.assertEqual(status, 200)
            self.assertEqual(own_list["capture_count"], 1)
            self.assertEqual(own_list["captures"][0]["capture_id"], capture_id)

            status, foreign_list = _get_json(
                connection,
                f"/v1/research/captures?operator_id={OPERATOR_ID}&security_id={FOREIGN_SECURITY_ID}",
            )
            self.assertEqual(status, 200)
            self.assertEqual(
                foreign_list["capture_count"],
                0,
                "a capture accepted for one security must never appear in "
                "another security's accepted-capture selector",
            )

            # 3. Immutable receipt survives a desktop restart against the same root.
            server.stop()
            restarted = _build_server(root)
            restarted.start()
            self.addCleanup(restarted.stop)
            restarted_parsed = urlsplit(restarted.origin)
            restarted_connection = HTTPConnection(
                restarted_parsed.hostname, restarted_parsed.port, timeout=2
            )
            status, reloaded = _get_json(
                restarted_connection,
                f"/v1/research/captures?operator_id={OPERATOR_ID}&security_id={SECURITY_ID}",
            )
            self.assertEqual(status, 200)
            self.assertEqual(reloaded["capture_count"], 1)
            self.assertEqual(reloaded["captures"][0]["capture_id"], capture_id)
            self.assertEqual(
                reloaded["captures"][0]["capture_revision"], capture_revision
            )
            self.assertEqual(
                reloaded["captures"][0]["capture_content_hash"],
                capture_content_hash,
            )

            status, reloaded_foreign = _get_json(
                restarted_connection,
                f"/v1/research/captures?operator_id={OPERATOR_ID}&security_id={FOREIGN_SECURITY_ID}",
            )
            self.assertEqual(status, 200)
            self.assertEqual(reloaded_foreign["capture_count"], 0)


if __name__ == "__main__":
    unittest.main()
