from __future__ import annotations

import unittest
from pathlib import Path


class PhaseOneMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob("*_iros_phase1_evidence_spine.sql")
        )
        if len(migrations) != 1:
            raise AssertionError("expected one Phase 1 evidence migration")
        cls.sql = migrations[0].read_text().lower()

    def test_creates_only_iros_evidence_objects(self) -> None:
        required = (
            "iros_research_runs",
            "iros_sources",
            "iros_source_documents",
            "iros_source_passages",
            "iros_claims",
            "iros_claim_evidence",
            "iros_v_claim_evidence_trace",
        )
        for name in required:
            self.assertIn(name, self.sql)

        forbidden_prefix = "we" + "ll_"
        self.assertNotIn(forbidden_prefix, self.sql)
        self.assertNotIn("grant all on all tables", self.sql)
        self.assertNotIn("grant all on schema public", self.sql)

    def test_enables_owner_scoped_rls_and_explicit_grants(self) -> None:
        self.assertEqual(
            self.sql.count("enable row level security"),
            6,
        )
        self.assertEqual(
            self.sql.count("using ((select auth.uid()) = operator_id)"),
            6,
        )
        self.assertIn("with (security_invoker = true)", self.sql)
        self.assertIn(
            "grant select on table public.iros_v_claim_evidence_trace "
            "to authenticated",
            " ".join(self.sql.split()),
        )

    def test_preserves_source_identity_and_uses_read_only_dashboard_grants(self) -> None:
        self.assertIn("source url and retrieval time are immutable", self.sql)
        self.assertIn(
            "filing identity, source url, and retrieval time are immutable",
            self.sql,
        )
        self.assertNotIn(
            "grant select, insert, update, delete "
            "on table public.iros_claims to authenticated",
            " ".join(self.sql.split()),
        )


if __name__ == "__main__":
    unittest.main()
