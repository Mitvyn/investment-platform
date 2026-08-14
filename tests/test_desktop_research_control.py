from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from http.client import HTTPConnection
from urllib.parse import urlencode, urlsplit

from workers.desktop.control import DesktopControlServer
from workers.desktop.research import AcceptedCaptureCatalog


class ResearchCatalogFake:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def list_captures(self, **values) -> AcceptedCaptureCatalog:
        self.calls.append(values)
        return AcceptedCaptureCatalog(captures=())


class DesktopResearchControlTests(unittest.TestCase):
    def test_lists_all_bounded_security_captures_without_implicit_selection(
        self,
    ) -> None:
        catalog = ResearchCatalogFake()
        server = DesktopControlServer(
            service=object(),
            control_token="control-secret",
            research_capture_catalog=catalog,
        )
        server.start()
        self.addCleanup(server.stop)
        query = urlencode(
            {
                "operator_id": "11111111-1111-4111-8111-111111111111",
                "security_id": "22222222-2222-4222-8222-222222222222",
            }
        )

        status, _payload = _request(
            server.origin,
            f"/v1/research/captures?{query}",
            token="control-secret",
        )

        self.assertEqual(status, 200)
        self.assertEqual(
            catalog.calls,
            [
                {
                    "operator_id": "11111111-1111-4111-8111-111111111111",
                    "security_id": "22222222-2222-4222-8222-222222222222",
                    "question_type_version": None,
                    "workflow_config_version": None,
                    "as_of_cutoff": None,
                    "max_count": 50,
                }
            ],
        )

    def test_lists_only_exact_operator_security_and_contract_captures(self) -> None:
        catalog = ResearchCatalogFake()
        server = DesktopControlServer(
            service=object(),
            control_token="control-secret",
            research_capture_catalog=catalog,
        )
        server.start()
        self.addCleanup(server.stop)
        query = urlencode(
            {
                "operator_id": "11111111-1111-4111-8111-111111111111",
                "security_id": "22222222-2222-4222-8222-222222222222",
                "question_type_version": ("biotech_moonshot_catalyst_assessment.v1"),
                "workflow_config_version": "biotech-moonshot-catalyst-v1",
                "as_of_cutoff": "2026-05-06T23:59:59+00:00",
            }
        )

        status, payload = _request(
            server.origin,
            f"/v1/research/captures?{query}",
            token="control-secret",
        )

        self.assertEqual(status, 200)
        self.assertEqual(
            payload["contract_version"], "accepted_research_capture_list.v1"
        )
        self.assertEqual(payload["capture_count"], 0)
        self.assertEqual(
            catalog.calls,
            [
                {
                    "operator_id": "11111111-1111-4111-8111-111111111111",
                    "security_id": "22222222-2222-4222-8222-222222222222",
                    "question_type_version": (
                        "biotech_moonshot_catalyst_assessment.v1"
                    ),
                    "workflow_config_version": "biotech-moonshot-catalyst-v1",
                    "as_of_cutoff": datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC),
                    "max_count": 50,
                }
            ],
        )


def _request(origin: str, path: str, *, token: str) -> tuple[int, dict[str, object]]:
    parsed = urlsplit(origin)
    connection = HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    connection.request(
        "GET",
        path,
        headers={"Authorization": f"Bearer {token}"},
    )
    response = connection.getresponse()
    return response.status, json.loads(response.read())


if __name__ == "__main__":
    unittest.main()
