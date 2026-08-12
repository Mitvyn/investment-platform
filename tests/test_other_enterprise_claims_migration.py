from __future__ import annotations

from pathlib import Path
import re
import unittest


MIGRATION = Path(
    "supabase/migrations/20260811120000_iros_other_enterprise_claims_v2.sql"
)


class OtherEnterpriseClaimsMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = MIGRATION.read_text()
        cls.normalized_sql = " ".join(cls.sql.split())

    def test_migration_versions_snapshot_and_persists_complete_claim_provenance(
        self,
    ) -> None:
        sql = self.sql
        normalized_sql = self.normalized_sql

        self.assertNotIn("well_", sql)
        for contract_version in (
            "valuation_snapshot.v2",
            "valuation_snapshot.personal_research.v2",
        ):
            self.assertIn(contract_version, sql)
        for input_type in (
            "included_cash",
            "reported_cash",
            "restricted_cash",
            "other_enterprise_claims",
        ):
            self.assertIn(f"'{input_type}'", sql)
        self.assertIn(
            "create table public.iros_valuation_other_claim_components",
            sql,
        )
        for component_id in (
            "redeemable_preferred_claim",
            "noncontrolling_interest_claim",
            "royalty_monetization_liability",
            "contingent_consideration_claim",
            "pension_underfunded_claim",
            "finance_lease_claim",
        ):
            self.assertIn(f"'{component_id}'", sql)
        self.assertIn(
            "execute function public.iros_guard_valuation_snapshot_component_change()",
            sql,
        )
        self.assertIn(
            "alter table public.iros_valuation_other_claim_components enable row level security",
            sql,
        )
        self.assertIn(
            "grant select, insert, update, delete on table "
            "public.iros_valuation_other_claim_components to service_role",
            normalized_sql,
        )

    def test_personal_contract_preserves_price_timestamp_identity(self) -> None:
        self.assertIn(
            "price_timestamp is not distinct from official_close_timestamp",
            self.normalized_sql,
        )

    def test_component_rows_remain_private_service_persistence(self) -> None:
        self.assertNotIn(
            "create view public.iros_v_valuation_other_claim_components",
            self.normalized_sql,
        )
        self.assertNotIn(
            "grant select on table public.iros_valuation_other_claim_components "
            "to authenticated",
            self.normalized_sql,
        )

    def test_finalizer_keeps_v1_and_adds_v2_formula_semantics(self) -> None:
        self.assertIn(
            "create or replace function "
            "public.iros_validate_valuation_snapshot_finalization()",
            self.normalized_sql,
        )
        self.assertIn(
            "new.valuation_contract_version in ( "
            "'valuation_snapshot.v2', "
            "'valuation_snapshot.personal_research.v2' )",
            self.normalized_sql,
        )
        self.assertIn(
            "new.enterprise_value <> new.market_capitalization + new.debt - new.cash",
            self.normalized_sql,
        )
        self.assertIn("enterprise-value-v1", self.sql)
        self.assertIn(
            "new.enterprise_value <> new.market_capitalization + new.debt "
            "+ other_enterprise_claims_value - new.cash",
            self.normalized_sql,
        )
        self.assertIn("enterprise-value-v2", self.sql)

    def test_v2_finalizer_requires_exact_capital_and_component_sets(self) -> None:
        for input_type in (
            "basic_shares_outstanding",
            "fully_diluted_shares",
            "included_cash",
            "reported_cash",
            "restricted_cash",
            "debt",
            "other_enterprise_claims",
        ):
            self.assertRegex(
                self.normalized_sql,
                rf"count\(\*\) filter \(\s*where c\.input_type = "
                rf"'{re.escape(input_type)}'\s*\) = 1",
            )
        self.assertIn(
            "capital_input_count <> 7 + jsonb_array_length( "
            "new.canonical_snapshot -> 'dilution_instruments' )",
            self.normalized_sql,
        )
        self.assertIn("other_claim_component_count <> 6", self.normalized_sql)
        for component_id in (
            "redeemable_preferred_claim",
            "noncontrolling_interest_claim",
            "royalty_monetization_liability",
            "contingent_consideration_claim",
            "pension_underfunded_claim",
            "finance_lease_claim",
        ):
            self.assertRegex(
                self.normalized_sql,
                rf"count\(\*\) filter \(\s*where c\.component_id = "
                rf"'{re.escape(component_id)}'\s*\) = 1",
            )
        self.assertIn(
            "other_claim_component_value is distinct from other_enterprise_claims_value",
            self.normalized_sql,
        )
        self.assertIn(
            "c.period_end is distinct from other_enterprise_claims_period_end",
            self.normalized_sql,
        )
        self.assertIn(
            "c.effective_at::date is distinct from c.period_end",
            self.normalized_sql,
        )

    def test_v2_component_evidence_must_belong_to_frozen_bundle(self) -> None:
        self.assertIn(
            "select unnest(c.supporting_evidence_ids) as evidence_id "
            "from public.iros_valuation_other_claim_components c",
            self.normalized_sql,
        )


if __name__ == "__main__":
    unittest.main()
