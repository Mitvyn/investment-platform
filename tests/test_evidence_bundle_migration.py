from __future__ import annotations

import unittest
from pathlib import Path


class EvidenceBundleMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob("*_iros_evidence_bundle.sql")
        )
        if len(migrations) != 1:
            raise AssertionError("expected one immutable evidence bundle migration")
        cls.sql = migrations[0].read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

    def test_creates_five_owner_scoped_artifact_tables_and_three_views(self) -> None:
        for name in (
            "iros_evidence_versions",
            "iros_evidence_bundles",
            "iros_evidence_bundle_items",
            "iros_evidence_bundle_gaps",
            "iros_research_run_evidence_bundles",
            "iros_v_research_run_evidence_bundle",
            "iros_v_evidence_bundle_manifest",
            "iros_v_evidence_bundle_gaps",
        ):
            self.assertIn(name, self.sql)

        self.assertEqual(self.sql.count("enable row level security"), 5)
        self.assertEqual(self.sql.count("with (security_invoker = true)"), 3)

    def test_isolates_iros_namespace_and_uses_explicit_grants(self) -> None:
        forbidden_prefix = "we" + "ll_"
        self.assertNotIn(forbidden_prefix, self.sql)
        self.assertNotIn("references public.w", self.sql)
        self.assertNotIn("grant all on schema public", self.sql)
        self.assertNotIn("grant all on all tables", self.sql)

        for table in (
            "iros_evidence_versions",
            "iros_evidence_bundles",
            "iros_evidence_bundle_items",
            "iros_evidence_bundle_gaps",
            "iros_research_run_evidence_bundles",
        ):
            self.assertIn(
                f"grant select on table public.{table} to authenticated",
                self.compact_sql,
            )
            self.assertNotIn(
                f"grant select, insert, update, delete on table public.{table} "
                "to authenticated",
                self.compact_sql,
            )

    def test_matches_evidence_bundle_wire_contract(self) -> None:
        for field in (
            "security_identity",
            "as_of_cutoff",
            "bundle_hash",
            "item_id",
            "item_version_id",
            "item_kind",
            "source_class",
            "source_locator",
            "locator",
            "content_sha256",
            "published_at",
            "retrieved_at",
            "effective_at",
            "filing_period_start",
            "filing_period_end",
            "freshness_state",
            "freshness_reason_code",
            "freshness_policy_version",
            "verified_metrics",
            "catalysts",
            "risks",
            "eligibility",
            "evidence_policy_version",
            "grader_ready",
            "gaps",
        ):
            self.assertIn(field, self.sql)

        for allowed_value in (
            "'sec'",
            "'issuer'",
            "'clinical'",
            "'regulatory'",
            "'financing'",
            "'passage'",
            "'metric'",
            "'catalyst'",
            "'risk'",
            "'current'",
            "'stale'",
            "'indeterminate'",
        ):
            self.assertIn(allowed_value, self.sql)

    def test_uses_content_identity_and_composite_owner_foreign_keys(self) -> None:
        self.assertIn("bundle_hash ~ '^[0-9a-f]{64}$'", self.sql)
        self.assertIn("content_sha256 ~ '^[0-9a-f]{64}$'", self.sql)
        self.assertIn(
            "unique (operator_id, bundle_hash)",
            self.compact_sql,
        )
        self.assertIn(
            "unique (operator_id, item_id, item_version_id)",
            self.compact_sql,
        )
        self.assertIn(
            "foreign key (operator_id, bundle_id)",
            self.compact_sql,
        )
        self.assertIn(
            "foreign key (operator_id, evidence_version_id)",
            self.compact_sql,
        )
        self.assertIn(
            "unique (operator_id, research_run_id)",
            self.compact_sql,
        )

    def test_finalization_enforces_cutoff_order_counts_and_readiness(self) -> None:
        self.assertIn(
            "evidence bundles must begin as draft",
            self.sql,
        )
        self.assertIn(
            "before insert on public.iros_evidence_bundles",
            self.compact_sql,
        )
        self.assertIn("evidence bundle finalization failed", self.sql)
        self.assertIn("published_at > new.as_of_cutoff", self.compact_sql)
        self.assertIn("effective_at > new.as_of_cutoff", self.compact_sql)
        self.assertIn(
            "filing_period_end > new.as_of_cutoff::date",
            self.compact_sql,
        )
        self.assertNotIn(
            "retrieved_at > new.as_of_cutoff",
            self.compact_sql,
        )
        self.assertIn("array_agg", self.sql)
        self.assertIn("order by i.ordinal", self.compact_sql)
        self.assertIn("manifest_count", self.sql)
        self.assertIn("gap_count", self.sql)
        self.assertIn("grader_ready", self.sql)
        self.assertIn("persistence_state = 'complete'", self.compact_sql)
        self.assertIn(
            "(new.eligibility ->> 'eligible')::boolean",
            self.compact_sql,
        )

    def test_run_link_requires_same_completed_eligible_run(self) -> None:
        self.assertIn("iros_eligibility_evaluations", self.sql)
        self.assertIn("e.eligible", self.sql)
        self.assertIn(
            "e.policy_version = b.eligibility ->> 'policy_version'",
            self.compact_sql,
        )
        self.assertIn("r.security_id = b.security_id", self.compact_sql)
        self.assertIn("r.as_of_cutoff = b.as_of_cutoff", self.compact_sql)

    def test_completed_artifacts_and_links_are_immutable(self) -> None:
        for message in (
            "evidence version is immutable",
            "frozen evidence bundle is immutable",
            "frozen evidence bundle items are immutable",
            "frozen evidence bundle gaps are immutable",
            "research run evidence bundle link is immutable",
        ):
            self.assertIn(message, self.sql)

        self.assertIn(
            "before insert or update or delete on public.iros_evidence_bundle_items",
            self.compact_sql,
        )
        self.assertIn(
            "before insert or update or delete on public.iros_evidence_bundle_gaps",
            self.compact_sql,
        )

    def test_owner_rls_hides_drafts_and_authenticated_access_is_read_only(
        self,
    ) -> None:
        self.assertGreaterEqual(
            self.sql.count("using ((select auth.uid()) = operator_id"),
            5,
        )
        self.assertIn("persistence_state = 'complete'", self.compact_sql)
        self.assertIn(
            "grant select on table public.iros_v_research_run_evidence_bundle "
            "to authenticated",
            self.compact_sql,
        )
        self.assertIn(
            "grant select on table public.iros_v_evidence_bundle_manifest "
            "to authenticated",
            self.compact_sql,
        )
        self.assertIn(
            "grant select on table public.iros_v_evidence_bundle_gaps "
            "to authenticated",
            self.compact_sql,
        )

    def test_composed_view_returns_one_exact_owner_scoped_contract_row(self) -> None:
        for field in (
            "operator_id",
            "research_run_id",
            "bundle_id",
            "bundle_hash",
            "canonical_bundle",
        ):
            self.assertIn(field, self.sql)
        self.assertIn("'contract_version', 'evidence_bundle.v1'", self.compact_sql)
        self.assertIn("jsonb_agg", self.sql)
        self.assertIn("order by i.ordinal", self.compact_sql)

    def test_replaces_research_run_policy_to_hide_committee_drafts(self) -> None:
        self.assertIn(
            "drop policy if exists iros_research_runs_operator_select",
            self.compact_sql,
        )
        self.assertIn(
            "run_type <> 'research_committee'",
            self.compact_sql,
        )
        self.assertIn(
            "persistence_state = 'complete'",
            self.compact_sql,
        )


if __name__ == "__main__":
    unittest.main()
