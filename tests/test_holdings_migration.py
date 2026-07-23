from __future__ import annotations

import unittest
from pathlib import Path


class HoldingsMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob("*_iros_private_holdings.sql")
        )
        if len(migrations) != 1:
            raise AssertionError("expected one private holdings migration")
        cls.sql = migrations[0].read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

    def test_exposes_only_complete_owner_scoped_immutable_holdings(self) -> None:
        self.assertIn("create table public.iros_holding_snapshots", self.compact_sql)
        self.assertIn("create table public.iros_holding_positions", self.compact_sql)
        self.assertIn("expected_position_count", self.sql)
        self.assertIn("count(*)", self.sql)
        self.assertIn("before update or delete", self.compact_sql)
        self.assertIn("enable row level security", self.compact_sql)
        self.assertIn("using ((select auth.uid()) = operator_id)", self.sql)
        self.assertIn("with (security_invoker = true)", self.sql)
        self.assertIn("iros_v_latest_holdings", self.sql)
        self.assertNotIn("well_", self.sql)
        self.assertNotIn(
            "grant insert on table public.iros_holding_snapshots to authenticated",
            self.compact_sql,
        )


if __name__ == "__main__":
    unittest.main()
