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
    def test_dry_run_reports_structurally_blocked_material_without_connection(
        self,
    ) -> None:
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
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["error"], "hosted_verification_dry_run_blocked")
        self.assertEqual(payload["reason"], "mutation_path_unreachable")
        self.assertEqual(len(payload["blocking_probe_ids"]), 21)
        self.assertIn("immutable.research_run", payload["blocking_probe_ids"])
        self.assertGreater(payload["migration_count"], 0)
        self.assertFalse(payload["connection_attempted"])

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

    def test_invalid_migration_gets_typed_machine_safe_reason(self) -> None:
        output = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            migration = Path(directory) / "20260811000000_iros_invalid.sql"
            migration.write_text("create table public.well_sessions (id uuid);\n")
            with redirect_stdout(output):
                exit_code = run(
                    ["dry-run", "--migration-root", directory],
                    environment={},
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["reason"], "migration_contract_invalid")
        self.assertFalse(payload["connection_attempted"])


if __name__ == "__main__":
    unittest.main()
