from __future__ import annotations

import unittest
from pathlib import Path


class MarketSeriesMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob("*_iros_market_series.sql")
        )
        if len(migrations) != 1:
            raise AssertionError("expected one market series migration")
        cls.sql = migrations[0].read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

        atomic_migrations = sorted(
            Path("supabase/migrations").glob(
                "*_iros_market_series_atomic_finalize.sql"
            )
        )
        if len(atomic_migrations) != 1:
            raise AssertionError("expected one market series atomic follow-up migration")
        cls.atomic_sql = atomic_migrations[0].read_text().lower()
        cls.atomic_compact_sql = " ".join(cls.atomic_sql.split())

    def test_adds_owner_scoped_immutable_ohlcv_bars(self) -> None:
        for field in (
            "security_id",
            "session_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "dividends",
            "stock_splits",
            "bar_sha256",
        ):
            self.assertIn(field, self.sql)
        self.assertIn("iros_market_bars", self.sql)
        self.assertIn("before update or delete", self.compact_sql)
        self.assertIn("using ((select auth.uid()) = operator_id)", self.sql)

    def test_exposes_security_invoker_latest_bar_view_read_only(self) -> None:
        self.assertIn("iros_v_market_series", self.sql)
        self.assertIn("with (security_invoker = true)", self.sql)
        self.assertIn(
            "grant select on table public.iros_v_market_series", self.compact_sql
        )
        self.assertNotIn(
            "grant select, insert, update, delete on table public.iros_market_bars to authenticated",
            self.compact_sql,
        )

    def test_incomplete_immutable_series_never_becomes_latest_visible_series(
        self,
    ) -> None:
        self.assertIn("expected_bar_count integer not null", self.compact_sql)
        self.assertIn("expected_bar_count > 0", self.compact_sql)
        self.assertIn("count(*)", self.compact_sql)
        self.assertIn("= s.expected_bar_count", self.compact_sql)

    def test_isolates_namespace_and_preserves_licensed_valuation_boundary(self) -> None:
        self.assertNotIn("well_", self.sql)
        self.assertNotIn("grant all on schema public", self.sql)
        valuation_contract = Path("packages/types/valuation-snapshot.ts").read_text()
        self.assertIn('"licensed_market_data"', valuation_contract)
        self.assertNotIn("yahoo_finance_via_yfinance", valuation_contract)

    def test_follow_up_scopes_snapshot_references_to_owner(self) -> None:
        self.assertIn(
            "unique (operator_id, id)",
            self.atomic_compact_sql,
        )
        self.assertIn(
            "foreign key (operator_id, snapshot_id) references public.iros_market_snapshots(operator_id, id)",
            self.atomic_compact_sql,
        )
        self.assertGreaterEqual(
            self.atomic_compact_sql.count(
                "foreign key (operator_id, snapshot_id) references public.iros_market_snapshots(operator_id, id)"
            ),
            2,
        )
        self.assertIn(
            "foreign key (operator_id, research_run_id) references public.iros_research_runs(operator_id, id)",
            self.atomic_compact_sql,
        )

    def test_follow_up_preserves_only_valid_existing_complete_series(self) -> None:
        self.assertIn("update public.iros_market_series s", self.atomic_compact_sql)
        self.assertIn("set persistence_state = 'complete'", self.atomic_compact_sql)
        self.assertIn("count(*)", self.atomic_compact_sql)
        self.assertIn("= s.expected_bar_count", self.atomic_compact_sql)
        self.assertIn("select min(b.session_date)", self.atomic_compact_sql)
        self.assertIn(") = s.session_start", self.atomic_compact_sql)
        self.assertIn("select max(b.session_date)", self.atomic_compact_sql)
        self.assertIn(") = s.session_end", self.atomic_compact_sql)
        self.assertIn("r.status = 'completed'", self.atomic_compact_sql)
        self.assertIn("r.persistence_state = 'complete'", self.atomic_compact_sql)

    def test_follow_up_finalizes_only_complete_series_through_service_rpc(self) -> None:
        for clause in (
            "add column persistence_state text not null default 'draft'",
            "create function public.iros_finalize_market_series",
            "security definer",
            "set search_path = ''",
            "count(*)",
            "expected_bar_count",
            "set persistence_state = 'complete'",
            "set status = 'completed'",
            "and s.persistence_state = 'complete'",
            "if selected_series.persistence_state = 'draft' then",
            "and persistence_state = 'draft'",
            "revoke all on function public.iros_finalize_market_series(uuid, uuid) from public, anon, authenticated",
            "grant execute on function public.iros_finalize_market_series(uuid, uuid) to service_role",
        ):
            self.assertIn(clause, self.atomic_compact_sql)


if __name__ == "__main__":
    unittest.main()
