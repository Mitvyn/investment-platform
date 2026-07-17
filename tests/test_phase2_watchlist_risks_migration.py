from __future__ import annotations

import unittest
from pathlib import Path


class PhaseTwoWatchlistRisksMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob(
                "*_iros_phase2_watchlist_risks.sql"
            )
        )
        if len(migrations) != 1:
            raise AssertionError("expected one Phase 2 watchlist/risks migration")
        cls.sql = migrations[0].read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

    def test_creates_only_iros_risk_and_watchlist_objects(self) -> None:
        for name in (
            "iros_risks",
            "iros_watchlist_items",
            "iros_v_risk_context",
        ):
            self.assertIn(name, self.sql)

        forbidden_prefix = "we" + "ll_"
        self.assertNotIn(forbidden_prefix, self.sql)
        self.assertNotIn("grant all on schema public", self.sql)

    def test_uses_rls_and_security_invoker(self) -> None:
        self.assertEqual(self.sql.count("enable row level security"), 2)
        self.assertIn("with (security_invoker = true)", self.sql)
        self.assertEqual(
            self.sql.count("using ((select auth.uid()) = operator_id)"),
            4,
        )
        self.assertEqual(
            self.sql.count("with check ((select auth.uid()) = operator_id)"),
            2,
        )

    def test_only_operator_managed_watchlist_is_authenticated_writable(self) -> None:
        self.assertIn(
            "grant select, insert, update, delete on table "
            "public.iros_watchlist_items to authenticated",
            self.compact_sql,
        )
        self.assertNotIn(
            "grant select, insert, update, delete on table "
            "public.iros_risks to authenticated",
            self.compact_sql,
        )


if __name__ == "__main__":
    unittest.main()
