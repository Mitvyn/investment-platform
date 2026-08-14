from __future__ import annotations

import unittest
from pathlib import Path

from workers.ids import stable_id


class PortfolioPersistRpcMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob("*_iros_portfolio_persist_rpc.sql")
        )
        if len(migrations) != 1:
            raise AssertionError("expected one portfolio persistence RPC migration")
        cls.sql = migrations[0].read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

    def test_pins_python_uuid5_parity_vectors(self) -> None:
        vectors = {
            "portfolio-account:moomoo_rest:private-account-2638": stable_id(
                "11111111-1111-4111-8111-111111111111",
                "portfolio-account",
                "moomoo_rest:private-account-2638",
            ),
            "portfolio-snapshot:sample": stable_id(
                "11111111-1111-4111-8111-111111111111",
                "portfolio-snapshot",
                "sample",
            ),
        }
        self.assertIn("create function public.iros_uuid5", self.compact_sql)
        self.assertIn("791c6c1a-c93f-4b41-889e-7e48032c9d70", self.sql)
        for identity, expected in vectors.items():
            with self.subTest(identity=identity):
                self.assertIn(expected, self.sql)

    def test_uuid5_uses_callable_bytea_slice_syntax(self) -> None:
        self.assertIn(
            "pg_catalog.substr(hash_bytes, 1, 16)",
            self.compact_sql,
        )
        self.assertNotIn(
            "pg_catalog.substring(hash_bytes from",
            self.compact_sql,
        )

    def test_owner_authenticated_rpc_recomputes_identity_before_writes(self) -> None:
        self.assertIn(
            "create function public.iros_persist_portfolio_broker_snapshot(",
            self.compact_sql,
        )
        body_start = self.compact_sql.index(
            "create function public.iros_persist_portfolio_broker_snapshot("
        )
        body = self.compact_sql[body_start:]
        owner_check = "p_operator_id is distinct from (select auth.uid())"
        first_insert = "insert into public.iros_portfolio_broker_accounts"
        self.assertIn(owner_check, body)
        self.assertLess(body.index(owner_check), body.index(first_insert))
        self.assertIn("expected_content_sha256", body)
        self.assertIn("expected_snapshot_id", body)
        self.assertIn("expected_request_sha256", body)
        self.assertIn("jsonb_array_length(p_positions)", body)
        self.assertIn("portfolio position order is noncanonical", body)

    def test_keeps_table_writes_closed_and_grants_only_rpc_execution(self) -> None:
        normalized_sql = self.compact_sql.replace("( ", "(").replace(" )", ")")
        signature = (
            "public.iros_persist_portfolio_broker_snapshot"
            "(uuid, jsonb, jsonb, jsonb, text, text, timestamptz)"
        )
        self.assertIn(
            f"grant execute on function {signature} to authenticated", normalized_sql
        )
        self.assertIn(
            f"revoke all on function {signature} from public, anon, authenticated",
            normalized_sql,
        )
        self.assertNotIn(
            "grant insert on table public.iros_portfolio_broker_snapshots to authenticated",
            self.compact_sql,
        )
        self.assertNotIn("well_", self.sql)
        self.assertNotIn("execute format", self.sql)


if __name__ == "__main__":
    unittest.main()
