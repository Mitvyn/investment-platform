from pathlib import Path
import unittest


class RawProviderAuditMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = list(
            Path("supabase/migrations").glob("*_iros_raw_provider_audit.sql")
        )
        assert len(migrations) == 1
        cls.sql = migrations[0].read_text().lower()

    def test_uses_trusted_permission_and_exact_owner_scope(self) -> None:
        self.assertIn("auth.jwt() -> 'app_metadata'", self.sql)
        self.assertIn("raw_provider_audit", self.sql)
        self.assertIn("auth.uid()", self.sql)
        self.assertNotIn("user_metadata", self.sql)
        self.assertIn("p_research_run_id", self.sql)

    def test_raw_tables_remain_ungranted_and_function_is_explicit(self) -> None:
        self.assertIn("security definer", self.sql)
        self.assertIn("set search_path = ''", self.sql)
        self.assertIn(
            "revoke execute on function public.iros_read_raw_provider_payload",
            self.sql,
        )
        self.assertIn("from public, anon", self.sql)
        self.assertIn("grant execute on function", self.sql)
        self.assertIn("to authenticated", self.sql)
        self.assertIn(
            "revoke all on table public.iros_model_attempt_payloads",
            self.sql,
        )
        self.assertIn(
            "revoke all on table public.iros_synthesis_attempt_payloads",
            self.sql,
        )

    def test_successful_read_inserts_immutable_access_event(self) -> None:
        self.assertIn(
            "create table public.iros_raw_provider_payload_access_events",
            self.sql,
        )
        self.assertIn("insert into public.iros_raw_provider_payload_access_events", self.sql)
        self.assertIn("before update or delete", self.sql)
        self.assertIn("enable row level security", self.sql)


if __name__ == "__main__":
    unittest.main()
