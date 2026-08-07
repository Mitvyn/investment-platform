from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from investment_research_os.hosted_verification import (
    IROS_REQUIRED_HOSTED_PROBE_IDS,
    build_default_iros_hosted_verification_plan,
)
from investment_research_os.hosted_verification_v3 import (
    build_default_iros_hosted_execution_contract,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_ROOT = REPO_ROOT / "supabase" / "migrations"


class HostedVerificationV3RegistryTests(unittest.TestCase):
    def test_default_registry_covers_every_required_probe_once(self) -> None:
        migration_paths = tuple(sorted(MIGRATION_ROOT.glob("*_iros_*.sql")))
        contract = build_default_iros_hosted_execution_contract(
            migration_paths=migration_paths,
        )
        legacy_plan = build_default_iros_hosted_verification_plan(
            migration_paths=migration_paths,
        )

        self.assertEqual(
            tuple(item.probe_id for item in contract.dispatches),
            tuple(sorted(IROS_REQUIRED_HOSTED_PROBE_IDS)),
        )
        self.assertEqual(
            contract.target_manifest_sha256,
            contract.execution_target_manifest_sha256,
        )
        self.assertIn(
            "iros_research_runs",
            {
                target
                for dispatch in contract.dispatches
                for target in dispatch.target_objects
            },
        )
        self.assertNotIn(
            "iros_research_runs",
            legacy_plan.target_objects,
        )
        self.assertTrue(contract.has_valid_content_hash())

    def test_default_registry_requires_every_dispatch_target_in_migrations(
        self,
    ) -> None:
        migration_paths = tuple(
            path
            for path in sorted(MIGRATION_ROOT.glob("*_iros_*.sql"))
            if path.name != "20260722040000_iros_operator_decisions.sql"
        )

        with self.assertRaisesRegex(
            ValueError,
            "dispatch target is absent from reviewed migrations",
        ):
            build_default_iros_hosted_execution_contract(
                migration_paths=migration_paths,
            )

    def test_commented_object_declaration_cannot_satisfy_target_discovery(
        self,
    ) -> None:
        migration_paths = tuple(
            path
            for path in sorted(MIGRATION_ROOT.glob("*_iros_*.sql"))
            if path.name != "20260722040000_iros_operator_decisions.sql"
        )
        with tempfile.TemporaryDirectory() as directory:
            comment_only = Path(directory) / "20260807000000_iros_comment_only.sql"
            comment_only.write_text(
                "-- create table public.iros_operator_decisions (id uuid);\n"
                "-- create table public.iros_workflow_commands (id uuid);\n"
                "-- create view public.iros_v_current_operator_decisions as select 1;\n"
                "-- create view public.iros_v_operator_decision_effects as select 1;\n"
                "-- create view public.iros_v_operator_decision_history as select 1;\n"
            )

            with self.assertRaisesRegex(
                ValueError,
                "dispatch target is absent from reviewed migrations",
            ):
                build_default_iros_hosted_execution_contract(
                    migration_paths=(*migration_paths, comment_only),
                )

    def test_every_mutating_default_probe_has_transaction_cleanup(self) -> None:
        contract = build_default_iros_hosted_execution_contract(
            migration_paths=tuple(sorted(MIGRATION_ROOT.glob("*_iros_*.sql"))),
        )
        fixtures = {item.fixture_id: item for item in contract.fixtures}

        for dispatch in contract.dispatches:
            if dispatch.operation not in {"attempt_insert", "attempt_update"}:
                continue
            self.assertEqual(dispatch.rollback_assertion, "required_and_verified")
            self.assertEqual(
                fixtures[dispatch.fixture_id].cleanup_rule,
                "transaction_rollback",
            )


if __name__ == "__main__":
    unittest.main()
