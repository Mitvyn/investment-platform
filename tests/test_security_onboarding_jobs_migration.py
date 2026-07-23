from __future__ import annotations

import unittest
from pathlib import Path

from investment_research_os.migration_audit import audit_iros_migration_batch


class SecurityOnboardingJobsMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob("*_iros_security_onboarding_jobs.sql")
        )
        if len(migrations) != 1:
            raise AssertionError("expected one security onboarding jobs migration")
        cls.sql = migrations[0].read_text().lower()

    def test_creates_owner_scoped_idempotent_jobs_with_narrow_enqueue_rpc(self) -> None:
        self.assertIn("create table public.iros_jobs", self.sql)
        self.assertIn("references auth.users(id) on delete restrict", self.sql)
        self.assertIn("check (job_type = 'security_onboarding')", self.sql)
        self.assertIn(
            "check (job_state in ('queued', 'running', 'completed', 'failed'))",
            self.sql,
        )
        self.assertIn("unique (operator_id, idempotency_key)", self.sql)
        self.assertIn("request_generation integer not null default 1", self.sql)
        self.assertIn("failure_retryable boolean", self.sql)
        self.assertIn(
            "unique (operator_id, ticker, request_generation)",
            self.sql,
        )
        self.assertIn(
            "or (selected_job.job_state = 'failed'\n"
            "      and selected_job.failure_retryable) then",
            self.sql,
        )
        self.assertNotIn(
            "selected_job.id is null or selected_job.job_state = 'failed'",
            self.sql,
        )
        self.assertIn("selected_generation := coalesce(", self.sql)
        self.assertIn("alter table public.iros_jobs enable row level security", self.sql)
        self.assertIn("using ((select auth.uid()) = operator_id)", self.sql)
        self.assertIn(
            "create function public.iros_enqueue_security_registration(\n  p_ticker text",
            self.sql,
        )
        self.assertNotIn("p_operator_id", self.sql)
        self.assertIn("caller_id := (select auth.uid())", self.sql)
        self.assertIn(
            "grant execute on function public.iros_enqueue_security_registration(text)\n  to authenticated",
            self.sql,
        )

    def test_service_worker_claims_and_finishes_fixed_jobs_without_dashboard_secret(self) -> None:
        self.assertIn("create table public.iros_job_attempts", self.sql)
        self.assertIn("for update skip locked", self.sql)
        self.assertIn("create function public.iros_claim_security_job(", self.sql)
        self.assertIn("create function public.iros_complete_security_job(", self.sql)
        self.assertIn("create function public.iros_fail_security_job(", self.sql)
        self.assertIn(
            "grant execute on function public.iros_claim_security_job(text)\n  to service_role",
            self.sql,
        )
        self.assertNotIn("grant update on table public.iros_jobs to authenticated", self.sql)
        self.assertNotIn(
            "grant select on table public.iros_jobs to authenticated", self.sql
        )
        self.assertNotIn(
            "grant select on table public.iros_job_attempts to authenticated",
            self.sql,
        )
        self.assertNotIn("child_process", self.sql)
        self.assertNotIn("argv", self.sql)
        self.assertNotIn("well_", self.sql)

    def test_passes_shared_iros_namespace_and_security_audit(self) -> None:
        migration = next(
            Path("supabase/migrations").glob(
                "*_iros_security_onboarding_jobs.sql"
            )
        )
        report = audit_iros_migration_batch((migration,))

        self.assertTrue(report.passed, report.violations)


if __name__ == "__main__":
    unittest.main()
