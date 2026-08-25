from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from investment_research_os.research_runs.file_storage import FileResearchRunRepository
from tests.test_primary_source_end_to_end import PLATFORM_CASE, request as integrated_request
from tests.test_primary_source_replay import _platform_capture_archive
from workers.desktop.control import DesktopControlServer
from workers.desktop.research_run import DesktopResearchRunService
from workers.primary_sources.captures import load_primary_source_capture
from workers.primary_sources.storage import FilePrimarySourceCaptureRepository


class DesktopResearchRunLoopbackTests(unittest.TestCase):
    def test_enqueue_executes_locally_and_progress_survives_service_reopen(self) -> None:
        operator_id = integrated_request(PLATFORM_CASE).operator_id
        clock_value = datetime(2026, 5, 7, 4, tzinfo=UTC)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captures = FilePrimarySourceCaptureRepository(root / "captures")
            archive = _platform_capture_archive()
            request = integrated_request(PLATFORM_CASE)
            persisted = captures.save_capture(
                load_primary_source_capture(
                    archive,
                    request=request,
                    trusted_issuer_hosts=PLATFORM_CASE.issuer_trusted_hosts,
                    accepted_at=lambda: datetime(2026, 5, 7, 3, tzinfo=UTC),
                ),
                archive,
            )

            service = DesktopResearchRunService(
                capture_repository=captures,
                command_root=root / "commands",
                research_run_root=root / "runs",
                evidence_bundle_root=root / "bundles",
                sec_user_agent="Investment Research OS research@example.com",
                clock=lambda: clock_value,
            )
            server = DesktopControlServer(
                service=object(),
                control_token="control-secret",
                research_run_service=service,
            )
            server.start()
            self.addCleanup(server.stop)

            body = {
                "operator_id": operator_id,
                "security_id": persisted.security_id,
                "ticker": PLATFORM_CASE.display_symbol,
                "question_type_version": persisted.question_type_version,
                "workflow_config_version": persisted.workflow_config_version,
                "as_of_cutoff": persisted.as_of_cutoff.isoformat(),
                "operator_focus": None,
                "capture_id": persisted.capture_id,
                "capture_revision": persisted.capture_revision,
                "capture_content_hash": persisted.capture_content_hash,
            }
            status, payload = _request(
                server.origin,
                "/v1/research/run/command",
                method="POST",
                token="control-secret",
                body=body,
            )
            self.assertEqual(status, 200)
            self.assertEqual(
                payload["contract_version"],
                "research_run_local_command_response.v1",
            )
            receipt = payload["receipt"]
            progress = payload["progress"]
            self.assertEqual(receipt["contract_version"], "research_run_local_command_receipt.v1")
            self.assertEqual(receipt["command_state"], "blocked")
            self.assertEqual(
                progress["completed_stages"],
                ["research_run", "evidence_bundle"],
            )
            command_id = receipt["command_id"]
            run_id = receipt["research_run_id"]
            self.assertIsNotNone(
                FileResearchRunRepository(root / "runs").get(
                    operator_id,
                    run_id,
                )
            )

            server.stop()
            reopened = DesktopResearchRunService(
                capture_repository=FilePrimarySourceCaptureRepository(root / "captures"),
                command_root=root / "commands",
                research_run_root=root / "runs",
                evidence_bundle_root=root / "bundles",
                sec_user_agent="Investment Research OS research@example.com",
                clock=lambda: clock_value,
            )
            reopened_server = DesktopControlServer(
                service=object(),
                control_token="control-secret",
                research_run_service=reopened,
            )
            reopened_server.start()
            self.addCleanup(reopened_server.stop)
            status, reopened_payload = _request(
                reopened_server.origin,
                "/v1/research/run/command?"
                + urlencode({"operator_id": operator_id, "command_id": command_id}),
                method="GET",
                token="control-secret",
            )

        self.assertEqual(status, 200)
        self.assertEqual(reopened_payload["receipt"]["command_id"], command_id)
        self.assertEqual(
            reopened_payload["progress"]["completed_stages"],
            ["research_run", "evidence_bundle"],
        )
        self.assertNotIn("lease_token", json.dumps(reopened_payload))
        self.assertNotIn(str(root), json.dumps(reopened_payload))


def _request(
    origin: str,
    path: str,
    *,
    method: str,
    token: str,
    body: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    parsed = urlsplit(origin)
    connection = HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    payload = None if body is None else json.dumps(body)
    headers = {"Authorization": f"Bearer {token}"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(payload.encode()))
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    return response.status, json.loads(response.read())


if __name__ == "__main__":
    unittest.main()
