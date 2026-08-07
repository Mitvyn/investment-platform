from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from workers.hosted_verification.__main__ import run


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_ROOT = REPO_ROOT / "supabase" / "migrations"


class HostedVerificationV3CliTests(unittest.TestCase):
    def test_dry_run_builds_complete_contract_without_connection_settings(self) -> None:
        output = StringIO()

        with redirect_stdout(output):
            exit_code = run(
                [
                    "dry-run",
                    "--migration-root",
                    str(MIGRATION_ROOT),
                ],
                environment={},
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            payload["contract_version"],
            "hosted-verification-execution-contract.v3",
        )
        self.assertEqual(payload["probe_count"], 32)
        self.assertEqual(payload["dispatch_count"], 32)
        self.assertGreater(payload["fixture_count"], 0)
        self.assertGreater(payload["migration_count"], 0)
        self.assertFalse(payload["connection_attempted"])
        self.assertEqual(len(payload["content_sha256"]), 64)

    def test_dry_run_failure_is_machine_safe(self) -> None:
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stdout(output):
                exit_code = run(
                    ["dry-run", "--migration-root", directory],
                    environment={"SUPABASE_SECRET_KEY": "must-not-appear"},
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["error"], "hosted_verification_dry_run_failed")
        self.assertEqual(payload["reason"], "migration_batch_empty")
        self.assertNotIn("must-not-appear", output.getvalue())


if __name__ == "__main__":
    unittest.main()
