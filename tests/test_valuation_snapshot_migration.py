from __future__ import annotations

import unittest
from pathlib import Path


class ValuationSnapshotMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob("*_iros_valuation_snapshot.sql")
        )
        if len(migrations) != 1:
            raise AssertionError("expected one composite valuation snapshot migration")
        cls.sql = migrations[0].read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

    def test_exposes_one_owner_scoped_snapshot_per_research_run(self) -> None:
        self.assertIn("create table public.iros_valuation_snapshots", self.sql)
        self.assertIn(
            "unique (operator_id, research_run_id)",
            self.compact_sql,
        )
        self.assertIn(
            "create view public.iros_v_research_run_valuation_snapshot",
            self.sql,
        )
        self.assertIn("with (security_invoker = true)", self.compact_sql)

    def test_persists_composite_inputs_calculations_and_materiality_once_per_bundle(
        self,
    ) -> None:
        for name in (
            "iros_valuation_capital_inputs",
            "iros_valuation_calculation_results",
            "iros_valuation_materiality_assessments",
            "iros_v_valuation_capital_inputs",
            "iros_v_valuation_calculation_results",
            "iros_v_valuation_materiality_assessments",
        ):
            self.assertIn(name, self.sql)

        self.assertIn(
            "unique (operator_id, evidence_bundle_id)",
            self.compact_sql,
        )
        self.assertEqual(self.sql.count("enable row level security"), 4)
        self.assertEqual(self.sql.count("with (security_invoker = true)"), 4)

    def test_matches_valuation_snapshot_v1_wire_contract(self) -> None:
        for field in (
            "evidence_bundle_hash",
            "security_id",
            "as_of_cutoff",
            "snapshot_status",
            "invalid_reason_codes",
            "currency",
            "price_type",
            "session_type",
            "session_date",
            "primary_listing_exchange",
            "share_price",
            "official_close_timestamp",
            "market_calendar_version",
            "market_status",
            "corporate_action_adjustment_status",
            "provider_source_reference_id",
            "basic_shares_outstanding",
            "fully_diluted_shares",
            "cash",
            "debt",
            "market_capitalization",
            "enterprise_value",
            "corporate_action_reconciliation",
            "price_information_state",
            "market_relative_analysis_permitted",
            "price_basis_policy_version",
            "freshness_policy_version",
            "materiality_policy_version",
            "canonical_snapshot",
        ):
            self.assertIn(field, self.sql)

        for value in (
            "'valuation_snapshot.v1'",
            "'valid'",
            "'invalid'",
            "'official_unadjusted_close'",
            "'regular_us_trading_session'",
            "'aligned'",
            "'pre_material_evidence'",
            "'indeterminate'",
        ):
            self.assertIn(value, self.sql)

    def test_preserves_capital_calculation_and_materiality_provenance(self) -> None:
        for field in (
            "input_id",
            "input_type",
            "value",
            "unit",
            "effective_at",
            "calculation_method",
            "formula",
            "calculation_id",
            "input_ids",
            "supporting_evidence_ids",
            "instrument_type",
            "calculation_type",
            "formula_version",
            "evidence_id",
            "publication_at",
            "timing_state",
            "market_materiality",
            "materiality_reason_code",
            "affected_domains",
        ):
            self.assertIn(field, self.sql)

        for value in (
            "'basic_shares_outstanding'",
            "'dilution_instrument'",
            "'fully_diluted_shares'",
            "'cash'",
            "'debt'",
            "'market_capitalization'",
            "'enterprise_value'",
            "'reported'",
            "'calculated'",
            "'material'",
            "'non_material'",
            "'before_or_at_close'",
            "'after_close_before_or_at_cutoff'",
        ):
            self.assertIn(value, self.sql)

        self.assertGreaterEqual(
            self.compact_sql.count(
                "foreign key (operator_id, valuation_snapshot_id)"
            ),
            3,
        )

    def test_draft_finalization_freezes_owner_linked_snapshot_and_children(
        self,
    ) -> None:
        for message in (
            "valuation snapshots must begin as draft",
            "valuation snapshot finalization failed",
            "valuation snapshot is immutable",
            "valuation snapshot components are immutable",
        ):
            self.assertIn(message, self.sql)

        self.assertIn(
            "before insert on public.iros_valuation_snapshots",
            self.compact_sql,
        )
        self.assertIn(
            "before update of persistence_state on public.iros_valuation_snapshots",
            self.compact_sql,
        )
        self.assertIn(
            "before update or delete on public.iros_valuation_snapshots",
            self.compact_sql,
        )
        for table in (
            "iros_valuation_capital_inputs",
            "iros_valuation_calculation_results",
            "iros_valuation_materiality_assessments",
        ):
            self.assertIn(
                f"before insert or update or delete on public.{table}",
                self.compact_sql,
            )

        self.assertIn("iros_research_run_evidence_bundles", self.sql)
        self.assertIn("b.persistence_state = 'complete'", self.compact_sql)
        self.assertIn("r.persistence_state = 'complete'", self.compact_sql)
        self.assertIn("b.bundle_hash = new.evidence_bundle_hash", self.compact_sql)

    def test_owner_rls_hides_drafts_and_authenticated_access_is_read_only(
        self,
    ) -> None:
        self.assertGreaterEqual(
            self.sql.count("using ((select auth.uid()) = operator_id"),
            4,
        )
        self.assertIn("persistence_state = 'complete'", self.compact_sql)

        for table in (
            "iros_valuation_snapshots",
            "iros_valuation_capital_inputs",
            "iros_valuation_calculation_results",
            "iros_valuation_materiality_assessments",
            "iros_v_research_run_valuation_snapshot",
            "iros_v_valuation_capital_inputs",
            "iros_v_valuation_calculation_results",
            "iros_v_valuation_materiality_assessments",
        ):
            self.assertIn(
                f"revoke all on table public.{table} from anon, authenticated",
                self.compact_sql,
            )
            self.assertIn(
                f"grant select on table public.{table} to authenticated",
                self.compact_sql,
            )
            self.assertNotIn(
                f"grant select, insert, update, delete on table public.{table} "
                "to authenticated",
                self.compact_sql,
            )

        self.assertNotIn("grant all on schema public", self.compact_sql)
        self.assertNotIn("grant all on all tables", self.compact_sql)
        self.assertNotIn("well_", self.sql)

    def test_finalization_validates_formulas_actions_and_information_alignment(
        self,
    ) -> None:
        for field in (
            "corporate_action_event_id",
            "corporate_action_event_type",
            "corporate_action_effective_at",
            "share_count_adjustment_status",
            "corporate_action_reconciliation_result",
        ):
            self.assertIn(field, self.sql)

        self.assertIn(
            "new.market_capitalization <> new.share_price * new.fully_diluted_shares",
            self.compact_sql,
        )
        self.assertIn(
            "new.enterprise_value <> new.market_capitalization + new.debt - new.cash",
            self.compact_sql,
        )
        self.assertIn("market-capitalization-v1", self.sql)
        self.assertIn("enterprise-value-v1", self.sql)
        self.assertIn("evidence_version_id", self.sql)
        self.assertIn("market_materiality = 'material'", self.compact_sql)
        self.assertIn(
            "timing_state = 'after_close_before_or_at_cutoff'",
            self.compact_sql,
        )
        self.assertIn("price_information_state = 'aligned'", self.compact_sql)
        self.assertIn("price_information_state = 'indeterminate'", self.compact_sql)

    def test_canonical_snapshot_identity_matches_relational_identity(self) -> None:
        for expression in (
            "new.canonical_snapshot ->> 'id' = new.id::text",
            "new.canonical_snapshot ->> 'operator_id' = new.operator_id::text",
            "new.canonical_snapshot ->> 'research_run_id' = new.research_run_id::text",
            "new.canonical_snapshot ->> 'evidence_bundle_id' = new.evidence_bundle_id::text",
            "new.canonical_snapshot ->> 'evidence_bundle_hash' = new.evidence_bundle_hash",
            "new.canonical_snapshot ->> 'security_id' = new.security_id::text",
            "new.canonical_snapshot ->> 'snapshot_status' = new.snapshot_status",
            "new.canonical_snapshot ->> 'price_information_state' = new.price_information_state",
        ):
            self.assertIn(expression, self.compact_sql)

        self.assertIn(
            "valuation snapshot finalization failed: canonical identity mismatch",
            self.sql,
        )

    def test_indexes_owner_scoped_foreign_key_access(self) -> None:
        self.assertIn(
            "create index iros_valuation_snapshots_operator_security_idx "
            "on public.iros_valuation_snapshots (operator_id, security_id)",
            self.compact_sql,
        )
        for identity in (
            "unique (operator_id, research_run_id)",
            "unique (operator_id, evidence_bundle_id)",
            "unique (operator_id, valuation_snapshot_id, input_id)",
            "unique (operator_id, valuation_snapshot_id, calculation_id)",
            "unique (operator_id, valuation_snapshot_id, evidence_id)",
        ):
            self.assertIn(identity, self.compact_sql)

    def test_capital_measures_retain_freshness_provenance(self) -> None:
        for field in (
            "freshness_state",
            "freshness_reason_code",
            "freshness_policy_version",
        ):
            self.assertIn(field, self.sql)
        for value in ("'current'", "'stale'", "'indeterminate'"):
            self.assertIn(value, self.sql)
        self.assertIn(
            "c.freshness_policy_version <> new.freshness_policy_version",
            self.compact_sql,
        )

    def test_requires_canonical_contract_keys_before_finalization(self) -> None:
        self.assertIn("canonical_snapshot ?& array[", self.compact_sql)
        for key in (
            "contract_version",
            "id",
            "operator_id",
            "research_run_id",
            "evidence_bundle_id",
            "evidence_bundle_hash",
            "security_id",
            "as_of_cutoff",
            "snapshot_status",
            "dilution_instruments",
            "calculation_ids",
            "evidence_materiality",
            "price_information_state",
            "created_at",
        ):
            self.assertIn(f"'{key}'", self.sql)


if __name__ == "__main__":
    unittest.main()
