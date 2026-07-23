from __future__ import annotations

from pathlib import Path
import re
import unittest


class StableSecurityContextMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        matches = list(
            Path("supabase/migrations").glob("*_iros_stable_security_context.sql")
        )
        if len(matches) != 1:
            raise AssertionError("expected one stable-security context migration")
        cls.sql = matches[0].read_text()
        cls.compact_sql = re.sub(r"\s+", " ", cls.sql.lower()).strip()

    def test_claim_evidence_view_uses_backfilled_stable_security_identity(self) -> None:
        self.assertIn("update public.iros_research_runs r", self.compact_sql)
        self.assertIn("set security_id = s.id", self.compact_sql)
        self.assertIn(
            "create view public.iros_v_security_claim_evidence_trace "
            "with (security_invoker = true)",
            self.compact_sql,
        )

    def test_issuer_and_market_context_views_filter_by_stable_security(self) -> None:
        for view_name in (
            "iros_v_security_financial_health",
            "iros_v_security_catalyst_context",
            "iros_v_security_risk_context",
            "iros_v_security_market_context",
        ):
            self.assertIn(
                f"create view public.{view_name} with (security_invoker = true)",
                self.compact_sql,
            )
            self.assertIn(
                f"revoke all on table public.{view_name} from anon, authenticated",
                self.compact_sql,
            )

        self.assertGreaterEqual(self.compact_sql.count("s.id as security_id"), 5)
        self.assertGreaterEqual(
            self.compact_sql.count(
                "join public.iros_research_runs run "
                "on run.id ="
            ),
            4,
        )

    def test_materialized_run_identity_has_owner_composite_foreign_key(self) -> None:
        self.assertIn(
            "add constraint iros_research_runs_security_fk "
            "foreign key (operator_id, security_id) "
            "references public.iros_securities(operator_id, id) on delete restrict",
            self.compact_sql,
        )

    def test_future_legacy_runs_materialize_exactly_one_registered_security(self) -> None:
        self.assertIn(
            "create function public.iros_materialize_research_run_security()",
            self.compact_sql,
        )
        self.assertIn(
            "if matched_count <> 1 then raise exception "
            "'research run requires exactly one registered security identity'",
            self.compact_sql,
        )
        self.assertIn("new.security_id := matched_security_id", self.compact_sql)
        self.assertIn(
            "create trigger iros_research_runs_materialize_security "
            "before insert on public.iros_research_runs",
            self.compact_sql,
        )
        self.assertIn(
            "revoke all on function public.iros_materialize_research_run_security() "
            "from public, anon",
            self.compact_sql,
        )
        self.assertIn(
            "if not exists ( select 1 from public.iros_securities supplied "
            "where supplied.operator_id = new.operator_id "
            "and supplied.id = new.security_id "
            "and supplied.symbol = new.ticker ) then raise exception "
            "'research run security identity does not match operator and ticker'",
            self.compact_sql,
        )
        self.assertIn("s.id as security_id", self.compact_sql)
        self.assertIn("s.symbol as ticker", self.compact_sql)
        self.assertIn("s.issuer_name as company_name", self.compact_sql)
        self.assertIn(
            "join public.iros_securities s on s.operator_id = r.operator_id "
            "and s.id = r.security_id",
            self.compact_sql,
        )
        self.assertIn(
            "revoke all on table public.iros_v_security_claim_evidence_trace "
            "from anon, authenticated",
            self.compact_sql,
        )


if __name__ == "__main__":
    unittest.main()
