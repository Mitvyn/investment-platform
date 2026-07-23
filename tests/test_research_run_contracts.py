from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from investment_research_os.research_runs import (
    normalize_research_question_request,
    parse_research_question_request,
)


FIXTURES = Path("tests/fixtures/contracts/research_run/v1")


class ResearchRunContractTests(unittest.TestCase):
    def test_research_run_package_imports_without_repository_worker_modules(
        self,
    ) -> None:
        environment = {
            **os.environ,
            "PYTHONPATH": str(Path("src").resolve()),
        }
        with tempfile.TemporaryDirectory() as working_directory:
            result = subprocess.run(
                [sys.executable, "-c", "import investment_research_os.research_runs"],
                cwd=working_directory,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_python_round_trips_question_and_normalized_request_fixtures(self) -> None:
        request_fixture = json.loads((FIXTURES / "request.json").read_text())
        normalized_fixture = json.loads(
            (FIXTURES / "normalized-request.json").read_text()
        )

        request = parse_research_question_request(request_fixture)
        normalized = normalize_research_question_request(request)

        self.assertEqual(request.as_dict(), request_fixture)
        self.assertEqual(normalized.as_dict(), normalized_fixture)

    def test_json_schema_locks_versioned_research_run_contract(self) -> None:
        schema = json.loads(Path("packages/types/research-run.schema.json").read_text())

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            schema["properties"]["contract_version"]["const"],
            "research_run.v1",
        )
        self.assertEqual(
            schema["properties"]["question_type"]["const"],
            "biotech_moonshot_catalyst_assessment",
        )
        self.assertEqual(
            schema["properties"]["workflow_config_version"]["const"],
            "biotech-moonshot-catalyst-v1",
        )
        self.assertFalse(schema["properties"]["eligibility"]["additionalProperties"])
        checks = schema["properties"]["eligibility"]["properties"]["checks"]
        self.assertEqual(len(checks["prefixItems"]), 9)
        self.assertFalse(checks["items"])
        self.assertNotIn(
            "pattern",
            schema["properties"]["security_identity"]["properties"]["cik"],
        )


if __name__ == "__main__":
    unittest.main()
