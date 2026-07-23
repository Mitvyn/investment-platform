from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_research_os.migration_audit import audit_iros_migration_batch


class IrosMigrationBatchAuditTests(unittest.TestCase):
    def test_rejects_empty_or_duplicate_batch_inputs(self) -> None:
        empty = audit_iros_migration_batch(())

        with TemporaryDirectory() as directory:
            path = Path(directory) / "20260722010000_iros_duplicate.sql"
            path.write_text("select 1;\n")
            duplicate = audit_iros_migration_batch((path, path))

        self.assertEqual(
            tuple(violation.rule_id for violation in empty.violations),
            ("batch.empty",),
        )
        self.assertEqual(
            tuple(violation.rule_id for violation in duplicate.violations),
            ("batch.duplicate_path",),
        )

    def test_returns_ordered_content_addressed_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "20260722010000_iros_first.sql"
            second = root / "20260722020000_iros_second.sql"
            first.write_text("select 1;\n")
            second.write_text("select 2;\n")

            report = audit_iros_migration_batch((second, first))

        self.assertTrue(report.passed)
        self.assertEqual(
            tuple(entry.path.name for entry in report.manifest),
            (first.name, second.name),
        )
        self.assertEqual(
            report.manifest[0].content_sha256,
            hashlib.sha256(b"select 1;\n").hexdigest(),
        )
        canonical_manifest = "".join(
            f"{entry.path.name}:{entry.content_sha256}\n"
            for entry in report.manifest
        ).encode()
        self.assertEqual(
            report.batch_sha256,
            hashlib.sha256(canonical_manifest).hexdigest(),
        )

    def test_rejects_non_iros_public_object_targets(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "20260722010000_iros_bad.sql"
            path.write_text(
                "create table public.well_intrusion (id uuid);\n"
                "alter table public.users add column unsafe boolean;\n"
            )

            report = audit_iros_migration_batch((path,))

        self.assertFalse(report.passed)
        self.assertEqual(
            tuple(violation.rule_id for violation in report.violations),
            ("namespace.public_object_prefix", "namespace.public_object_prefix"),
        )

    def test_rejects_cross_project_schema_references(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "20260722010000_iros_cross_project.sql"
            path.write_text(
                "create table public.iros_records (\n"
                "  id uuid references wellness.users(id)\n"
                ");\n"
                "alter table public.iros_records enable row level security;\n"
                "revoke all on table public.iros_records "
                "from public, anon, authenticated;\n"
            )

            report = audit_iros_migration_batch((path,))

        self.assertEqual(
            tuple(violation.rule_id for violation in report.violations),
            ("namespace.cross_project_schema",),
        )

    def test_rejects_schema_wide_and_default_privilege_grants(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "20260722010000_iros_bad_grants.sql"
            path.write_text(
                "grant usage on schema public to authenticated;\n"
                "alter default privileges in schema public "
                "grant select on tables to authenticated;\n"
            )

            report = audit_iros_migration_batch((path,))

        self.assertEqual(
            tuple(violation.rule_id for violation in report.violations),
            ("grants.schema_wide", "grants.default_privileges"),
        )

    def test_requires_rls_for_created_tables_and_security_invoker_views(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "20260722010000_iros_unsafe_exposure.sql"
            path.write_text(
                "create table public.iros_unprotected (id uuid);\n"
                "create view public.iros_unsafe_view as "
                "select id from public.iros_unprotected;\n"
            )

            report = audit_iros_migration_batch((path,))

        self.assertEqual(
            tuple(violation.rule_id for violation in report.violations),
            (
                "rls.created_table_missing",
                "grants.explicit_revoke_missing",
                "views.security_invoker_missing",
                "grants.explicit_revoke_missing",
            ),
        )

    def test_requires_explicit_anon_and_authenticated_revokes(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "20260722010000_iros_missing_revokes.sql"
            path.write_text(
                "create table public.iros_records (id uuid);\n"
                "alter table public.iros_records enable row level security;\n"
                "create view public.iros_records_view "
                "with (security_invoker = true) as "
                "select id from public.iros_records;\n"
            )

            report = audit_iros_migration_batch((path,))

        self.assertEqual(
            tuple(violation.rule_id for violation in report.violations),
            ("grants.explicit_revoke_missing", "grants.explicit_revoke_missing"),
        )

    def test_exact_eleven_file_operator_review_batch_passes_static_audit(self) -> None:
        names = (
            "20260722012640_iros_grader_execution.sql",
            "20260722020030_iros_five_grader_committee.sql",
            "20260722022429_iros_committee_memo.sql",
            "20260722024500_iros_yfinance_market_provider.sql",
            "20260722030000_iros_readiness_thesis.sql",
            "20260722040000_iros_operator_decisions.sql",
            "20260722050000_iros_market_series.sql",
            "20260722112946_iros_raw_provider_audit.sql",
            "20260722113326_iros_readiness_valuation_gate.sql",
            "20260722120000_iros_market_series_atomic_finalize.sql",
            "20260722204027_iros_stable_security_context.sql",
        )
        paths = tuple(Path("supabase/migrations") / name for name in names)

        report = audit_iros_migration_batch(reversed(paths))

        self.assertTrue(report.passed, report.violations)
        self.assertEqual(
            tuple(entry.path.name for entry in report.manifest),
            names,
        )
        self.assertRegex(report.batch_sha256, r"^[0-9a-f]{64}$")

    def test_security_definer_requires_empty_search_path_and_execute_revoke(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "20260722010000_iros_unsafe_function.sql"
            path.write_text(
                "create function public.iros_unsafe() returns void "
                "language plpgsql security definer as $$ "
                "begin return; end; $$;\n"
            )

            report = audit_iros_migration_batch((path,))

        self.assertEqual(
            tuple(violation.rule_id for violation in report.violations),
            (
                "functions.security_definer_search_path",
                "functions.execute_revoke_missing",
            ),
        )


if __name__ == "__main__":
    unittest.main()
