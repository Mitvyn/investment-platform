from pathlib import Path
import unittest


class ReadinessValuationGateMigrationTests(unittest.TestCase):
    def test_adds_aligned_valuation_check_to_persisted_readiness_set(self) -> None:
        migrations = list(
            Path("supabase/migrations").glob(
                "*_iros_readiness_valuation_gate.sql"
            )
        )
        self.assertEqual(len(migrations), 1)
        sql = migrations[0].read_text()
        self.assertIn("'aligned_valuation_snapshot_required'", sql)
        self.assertIn("persisted_check_count <> 11", sql)
        self.assertIn("canonical_check_count <> 11", sql)


if __name__ == "__main__":
    unittest.main()
