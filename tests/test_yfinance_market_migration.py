from __future__ import annotations

import unittest
from pathlib import Path


class YFinanceMarketMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob(
                "*_iros_yfinance_market_provider.sql"
            )
        )
        if len(migrations) != 1:
            raise AssertionError("expected one yfinance provider migration")
        cls.sql = migrations[0].read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

    def test_adds_personal_use_provider_without_removing_legacy_rows(self) -> None:
        self.assertIn(
            "alter table public.iros_market_snapshots",
            self.compact_sql,
        )
        self.assertIn("'twelve_data'", self.sql)
        self.assertIn("'yahoo_finance_via_yfinance'", self.sql)
        self.assertIn("iros_market_snapshots_provider", self.sql)

    def test_touches_only_iros_objects(self) -> None:
        self.assertNotIn("well_", self.sql)
        self.assertNotIn("references public.", self.sql)

    def test_personal_feed_does_not_weaken_valuation_readiness_contract(
        self,
    ) -> None:
        contract = Path("packages/types/valuation-snapshot.ts").read_text()
        self.assertIn('"licensed_market_data"', contract)
        self.assertNotIn("yahoo_finance_via_yfinance", contract)


if __name__ == "__main__":
    unittest.main()
