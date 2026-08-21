from __future__ import annotations

import json
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlsplit

from workers.desktop.control import DesktopControlServer
from workers.desktop.research_notebook import (
    DesktopResearchNotebook,
    TickerNotebookError,
)

SECURITY_A = "11111111-1111-4111-8111-111111111111"
SECURITY_B = "22222222-2222-4222-8222-222222222222"


class DesktopResearchNotebookRepositoryTests(unittest.TestCase):
    def test_note_written_for_one_security_reloads_and_never_leaks_to_another(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "ticker-notebook.sqlite3"
            notebook = DesktopResearchNotebook(database_path)

            written = notebook.add_note(SECURITY_A, "  Watch financing runway.  ")
            self.assertEqual(written["security_id"], SECURITY_A)
            self.assertEqual(written["author_role"], "operator")
            self.assertEqual(written["body"], "Watch financing runway.")

            self.assertEqual(
                [note["body"] for note in notebook.list_notes(SECURITY_A)],
                ["Watch financing runway."],
            )
            self.assertEqual(notebook.list_notes(SECURITY_B), ())

            reloaded = DesktopResearchNotebook(database_path)
            self.assertEqual(
                [note["body"] for note in reloaded.list_notes(SECURITY_A)],
                ["Watch financing runway."],
            )
            self.assertEqual(reloaded.list_notes(SECURITY_B), ())

    def test_list_order_is_deterministic_newest_or_oldest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            notebook = DesktopResearchNotebook(
                Path(temporary_directory) / "ticker-notebook.sqlite3"
            )
            notebook.add_note(SECURITY_A, "first")
            notebook.add_note(SECURITY_A, "second")

            newest = [note["body"] for note in notebook.list_notes(SECURITY_A, order="newest")]
            oldest = [note["body"] for note in notebook.list_notes(SECURITY_A, order="oldest")]
            self.assertEqual(oldest, ["first", "second"])
            self.assertEqual(newest, list(reversed(oldest)))

    def test_bounds_list_to_at_most_one_hundred_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            notebook = DesktopResearchNotebook(
                Path(temporary_directory) / "ticker-notebook.sqlite3"
            )
            for index in range(120):
                notebook.add_note(SECURITY_A, f"note {index}")
            self.assertEqual(len(notebook.list_notes(SECURITY_A)), 100)

    def test_rejects_invalid_security_id_empty_oversized_and_control_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            notebook = DesktopResearchNotebook(
                Path(temporary_directory) / "ticker-notebook.sqlite3"
            )
            with self.assertRaises(TickerNotebookError):
                notebook.add_note("not-a-uuid", "hello")
            with self.assertRaises(TickerNotebookError):
                notebook.add_note(SECURITY_A, "   ")
            with self.assertRaises(TickerNotebookError):
                notebook.add_note(SECURITY_A, "x" * 4_001)
            with self.assertRaises(TickerNotebookError):
                notebook.add_note(SECURITY_A, "bad\x00control")
            with self.assertRaises(TickerNotebookError):
                notebook.list_notes("not-a-uuid")


class DesktopResearchNotebookLoopbackTests(unittest.TestCase):
    def test_loopback_requires_bearer_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            notebook = DesktopResearchNotebook(
                Path(temporary_directory) / "ticker-notebook.sqlite3"
            )
            server = DesktopControlServer(
                service=object(),  # type: ignore[arg-type]
                control_token="control-secret",
                research_notebook=notebook,
            )
            server.start()
            self.addCleanup(server.stop)
            parsed = urlsplit(server.origin)
            connection = HTTPConnection(parsed.hostname, parsed.port, timeout=1)
            connection.request(
                "GET", f"/v1/research/notebook?security_id={SECURITY_A}"
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 401)
            self.assertEqual(response.read(), b'{"error":"desktop_control_unauthorized"}')

    def test_loopback_post_then_get_is_isolated_per_security_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            notebook = DesktopResearchNotebook(
                Path(temporary_directory) / "ticker-notebook.sqlite3"
            )
            server = DesktopControlServer(
                service=object(),  # type: ignore[arg-type]
                control_token="control-secret",
                research_notebook=notebook,
            )
            server.start()
            self.addCleanup(server.stop)
            parsed = urlsplit(server.origin)
            connection = HTTPConnection(parsed.hostname, parsed.port, timeout=1)

            connection.request(
                "POST",
                "/v1/research/notebook",
                body=json.dumps(
                    {"security_id": SECURITY_A, "body": "Financing runway note"}
                ),
                headers={
                    "Authorization": "Bearer control-secret",
                    "Content-Type": "application/json",
                },
            )
            post_response = connection.getresponse()
            self.assertEqual(post_response.status, 200)
            posted = json.loads(post_response.read())
            self.assertEqual(posted["contract_version"], "ticker_notebook_note.v1")
            self.assertEqual(posted["security_id"], SECURITY_A)
            self.assertEqual(posted["author_role"], "operator")
            self.assertEqual(posted["body"], "Financing runway note")
            self.assertIn("note_id", posted)
            self.assertIn("created_at", posted)

            connection.request(
                "GET",
                f"/v1/research/notebook?security_id={SECURITY_A}",
                headers={"Authorization": "Bearer control-secret"},
            )
            listed = json.loads(connection.getresponse().read())
            self.assertEqual(listed["contract_version"], "ticker_notebook_list.v1")
            self.assertEqual(listed["order"], "newest")
            self.assertEqual(len(listed["notes"]), 1)
            self.assertEqual(listed["notes"][0]["body"], "Financing runway note")

            connection.request(
                "GET",
                f"/v1/research/notebook?security_id={SECURITY_B}",
                headers={"Authorization": "Bearer control-secret"},
            )
            other_security = json.loads(connection.getresponse().read())
            self.assertEqual(other_security["notes"], [])

    def test_loopback_rejects_malformed_post_and_unavailable_notebook(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            notebook = DesktopResearchNotebook(
                Path(temporary_directory) / "ticker-notebook.sqlite3"
            )
            server = DesktopControlServer(
                service=object(),  # type: ignore[arg-type]
                control_token="control-secret",
                research_notebook=notebook,
            )
            server.start()
            self.addCleanup(server.stop)
            parsed = urlsplit(server.origin)
            connection = HTTPConnection(parsed.hostname, parsed.port, timeout=1)

            connection.request(
                "POST",
                "/v1/research/notebook",
                body=json.dumps({"security_id": SECURITY_A, "body": ""}),
                headers={
                    "Authorization": "Bearer control-secret",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            self.assertEqual(
                response.read(), b'{"error":"ticker_notebook_request_invalid"}'
            )

            connection.request(
                "POST",
                "/v1/research/notebook",
                body=json.dumps({"security_id": "not-a-uuid", "body": "x"}),
                headers={
                    "Authorization": "Bearer control-secret",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 400)

            connection.request(
                "GET",
                "/v1/research/notebook?security_id=not-a-uuid",
                headers={"Authorization": "Bearer control-secret"},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()

            server_without_notebook = DesktopControlServer(
                service=object(),  # type: ignore[arg-type]
                control_token="control-secret",
            )
            server_without_notebook.start()
            self.addCleanup(server_without_notebook.stop)
            parsed = urlsplit(server_without_notebook.origin)
            connection = HTTPConnection(parsed.hostname, parsed.port, timeout=1)
            connection.request(
                "GET",
                f"/v1/research/notebook?security_id={SECURITY_A}",
                headers={"Authorization": "Bearer control-secret"},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 503)
            response.read()


if __name__ == "__main__":
    unittest.main()
