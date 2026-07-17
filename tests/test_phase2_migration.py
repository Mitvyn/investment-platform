from __future__ import annotations

import unittest
from pathlib import Path


class PhaseTwoMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob("*_iros_phase2_ticker_context.sql")
        )
        if len(migrations) != 1:
            raise AssertionError("expected one Phase 2 ticker context migration")
        cls.sql = migrations[0].read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

    def test_creates_only_iros_phase2_objects(self) -> None:
        required = (
            "iros_issuer_releases",
            "iros_issuer_passages",
            "iros_financial_metrics",
            "iros_catalysts",
            "iros_market_snapshots",
            "iros_v_financial_health",
            "iros_v_catalyst_context",
            "iros_v_market_context",
        )
        for name in required:
            self.assertIn(name, self.sql)

        forbidden_prefix = "we" + "ll_"
        self.assertNotIn(forbidden_prefix, self.sql)
        self.assertNotIn("grant all on all tables", self.sql)
        self.assertNotIn("grant all on schema public", self.sql)

    def test_uses_owner_scoped_rls_security_invoker_views_and_explicit_grants(
        self,
    ) -> None:
        self.assertEqual(self.sql.count("enable row level security"), 5)
        self.assertEqual(
            self.sql.count("using ((select auth.uid()) = operator_id)"),
            5,
        )
        self.assertEqual(self.sql.count("with (security_invoker = true)"), 3)
        self.assertIn(
            "grant select on table public.iros_v_financial_health "
            "to authenticated",
            self.compact_sql,
        )

    def test_preserves_source_identity_and_calculation_provenance(self) -> None:
        self.assertIn("source url and retrieval time are immutable", self.sql)
        self.assertIn("metric_kind in ('reported', 'calculated')", self.sql)
        self.assertIn("metric_kind = 'calculated'", self.sql)
        self.assertIn("source_period text not null", self.sql)
        self.assertIn("formula text", self.sql)

    def test_authenticated_role_remains_read_only(self) -> None:
        self.assertNotIn(
            "grant select, insert, update, delete on table "
            "public.iros_market_snapshots to authenticated",
            self.compact_sql,
        )


if __name__ == "__main__":
    unittest.main()
