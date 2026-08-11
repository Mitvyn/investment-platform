from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from investment_research_os.hosted_verification import (
    IROS_REQUIRED_HOSTED_PROBE_IDS,
)
from investment_research_os.hosted_verification_v3 import (
    HostedVerificationContractError,
    build_default_iros_hosted_execution_contract,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_ROOT = REPO_ROOT / "supabase" / "migrations"


class HostedVerificationV3RegistryTests(unittest.TestCase):
    def test_default_registry_refuses_unreachable_mutating_probe_material(self) -> None:
        migration_paths = tuple(sorted(MIGRATION_ROOT.glob("*_iros_*.sql")))
        with self.assertRaises(HostedVerificationContractError) as caught:
            build_default_iros_hosted_execution_contract(
                migration_paths=migration_paths,
            )

        self.assertEqual(caught.exception.reason_code, "mutation_path_unreachable")
        self.assertEqual(
            caught.exception.blocking_probe_ids,
            tuple(
                sorted(
                    probe_id
                    for probe_id in IROS_REQUIRED_HOSTED_PROBE_IDS
                    if probe_id.startswith(("immutable.", "duplicate.", "valuation."))
                )
            ),
        )

    def test_default_registry_requires_every_dispatch_target_in_migrations(
        self,
    ) -> None:
        migration_paths = tuple(
            path
            for path in sorted(MIGRATION_ROOT.glob("*_iros_*.sql"))
            if path.name != "20260722040000_iros_operator_decisions.sql"
        )

        with self.assertRaises(HostedVerificationContractError) as caught:
            build_default_iros_hosted_execution_contract(
                migration_paths=migration_paths,
            )
        self.assertEqual(caught.exception.reason_code, "dispatch_target_absent")

    def test_privileged_invoker_probe_requires_target_table_privileges(self) -> None:
        migration_paths = tuple(sorted(MIGRATION_ROOT.glob("*_iros_*.sql")))
        with tempfile.TemporaryDirectory() as directory:
            revoke = Path(directory) / "20260811999999_iros_revoke_probe_target.sql"
            revoke.write_text(
                "revoke update on table public.iros_research_runs from service_role;\n"
            )

            with self.assertRaises(HostedVerificationContractError) as caught:
                build_default_iros_hosted_execution_contract(
                    migration_paths=(*migration_paths, revoke),
                )

        self.assertEqual(caught.exception.reason_code, "mutation_path_unreachable")
        self.assertIn(
            "immutable.research_run",
            caught.exception.blocking_probe_ids,
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

            with self.assertRaises(HostedVerificationContractError) as caught:
                build_default_iros_hosted_execution_contract(
                    migration_paths=(*migration_paths, comment_only),
                )
            self.assertEqual(caught.exception.reason_code, "dispatch_target_absent")


if __name__ == "__main__":
    unittest.main()
