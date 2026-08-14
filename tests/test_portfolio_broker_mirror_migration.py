from __future__ import annotations

import unittest
from pathlib import Path


class PortfolioBrokerMirrorMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob("*_iros_portfolio_broker_mirror.sql")
        )
        if len(migrations) != 1:
            raise AssertionError("expected one portfolio broker mirror migration")
        cls.sql = migrations[0].read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

    def test_declares_portfolio_owned_immutable_mirror(self) -> None:
        for table in (
            "iros_portfolio_broker_accounts",
            "iros_portfolio_broker_snapshots",
            "iros_portfolio_broker_positions",
            "iros_portfolio_broker_sync_receipts",
        ):
            with self.subTest(table=table):
                self.assertIn(f"create table public.{table}", self.compact_sql)
                self.assertIn(
                    f"alter table public.{table} enable row level security",
                    self.compact_sql,
                )
        self.assertIn("iros_v_portfolio_latest_broker_positions", self.sql)
        self.assertIn("with (security_invoker = true)", self.sql)
        self.assertIn(
            "before update on public.iros_portfolio_broker_snapshots",
            self.compact_sql,
        )
        self.assertIn(
            "before delete on public.iros_portfolio_broker_snapshots",
            self.compact_sql,
        )
        self.assertIn("persistence_state", self.sql)
        self.assertIn("expected_position_count", self.sql)
        self.assertIn("count(*)", self.sql)
        self.assertIn("portfolio broker snapshot account contract mismatch", self.sql)

    def test_guards_position_and_receipt_inserts_at_database_boundary(self) -> None:
        self.assertIn(
            "create function public.iros_validate_portfolio_broker_position_insert()",
            self.compact_sql,
        )
        self.assertIn(
            "before insert on public.iros_portfolio_broker_positions",
            self.compact_sql,
        )
        self.assertIn("snapshot.persistence_state <> 'draft'", self.sql)
        self.assertIn(
            "create function public.iros_validate_portfolio_broker_sync_receipt()",
            self.compact_sql,
        )
        self.assertIn(
            "before insert on public.iros_portfolio_broker_sync_receipts",
            self.compact_sql,
        )
        self.assertIn("snapshot.persistence_state <> 'complete'", self.sql)

    def test_keeps_provider_identity_private_and_security_identity_decoupled(
        self,
    ) -> None:
        self.assertIn("account_ref", self.sql)
        self.assertNotIn("provider_account_id", self.sql)
        self.assertNotIn("account_number", self.sql)
        self.assertNotIn("card_number", self.sql)
        self.assertNotIn("references public.iros_securities", self.compact_sql)
        self.assertNotIn("well_", self.sql)

    def test_preserves_exact_decimal_strings_and_mapping_states(self) -> None:
        self.assertIn("quantity_text text not null", self.compact_sql)
        self.assertIn("display_name text not null", self.compact_sql)
        self.assertIn("market_value_text text not null", self.compact_sql)
        self.assertIn("mapping_state text not null", self.compact_sql)
        self.assertIn("'mapped', 'unmapped', 'ambiguous'", self.compact_sql)
        self.assertIn("security_id is null", self.compact_sql)
        self.assertIn("security_id is not null", self.compact_sql)
        self.assertIn("content_sha256", self.sql)

    def test_allows_owner_reads_but_no_authenticated_writes(self) -> None:
        self.assertIn("using ((select auth.uid()) = operator_id)", self.sql)
        self.assertIn(
            "grant select on table public.iros_v_portfolio_latest_broker_positions to authenticated",
            self.compact_sql,
        )
        self.assertNotIn(
            "grant insert on table public.iros_portfolio_broker_snapshots to authenticated",
            self.compact_sql,
        )
        self.assertNotIn(
            "grant update on table public.iros_portfolio_broker_snapshots to authenticated",
            self.compact_sql,
        )
        self.assertIn(
            "grant select, insert, update on table public.iros_portfolio_broker_snapshots to service_role",
            self.compact_sql,
        )


if __name__ == "__main__":
    unittest.main()
