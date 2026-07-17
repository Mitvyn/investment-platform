from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


class DashboardContractTests(unittest.TestCase):
    def test_fixture_preserves_exact_sec_trace(self) -> None:
        fixture = json.loads(
            Path("apps/dashboard/data/rxrx-trace.json").read_text()
        )

        self.assertEqual(fixture["ticker"], "RXRX")
        self.assertEqual(fixture["verificationState"], "supported")
        self.assertEqual(
            fixture["sourceUrl"],
            "https://www.sec.gov/Archives/edgar/data/1601830/"
            "000160183025000127/rxrx-20250630.htm",
        )
        self.assertIn("$525.1 million", fixture["passage"])
        self.assertEqual(
            fixture["passageSha256"],
            hashlib.sha256(fixture["passage"].encode()).hexdigest(),
        )

    def test_dashboard_has_no_service_role_credential_path(self) -> None:
        source_paths = [
            *Path("apps/dashboard/app").rglob("*.ts"),
            *Path("apps/dashboard/app").rglob("*.tsx"),
            *Path("apps/dashboard/lib").rglob("*.ts"),
            Path("apps/dashboard/proxy.ts"),
            Path("apps/dashboard/next.config.ts"),
        ]
        dashboard_text = "\n".join(
            path.read_text() for path in source_paths
        ).lower()

        forbidden = "service" + "_role"
        self.assertNotIn(forbidden, dashboard_text)
        self.assertIn("@supabase/ssr", dashboard_text)
        self.assertIn("getclaims", dashboard_text)
        self.assertNotIn("iros_access_token", dashboard_text)
        self.assertIn("shouldcreateuser: false", dashboard_text)

    def test_runtime_evidence_path_does_not_fall_back_to_fixture(self) -> None:
        evidence_module = Path("apps/dashboard/lib/evidence.ts").read_text()

        self.assertIn('from("iros_v_claim_evidence_trace")', evidence_module)
        self.assertNotIn("rxrx-trace.json", evidence_module)

    def test_phase2_context_uses_authenticated_security_invoker_views(self) -> None:
        context_module = Path("apps/dashboard/lib/context.ts").read_text()

        self.assertIn('from("iros_v_financial_health")', context_module)
        self.assertIn('from("iros_v_catalyst_context")', context_module)
        self.assertIn('from("iros_v_market_context")', context_module)
        self.assertIn('from("iros_v_risk_context")', context_module)
        self.assertNotIn("TWELVE_DATA_API_KEY", context_module)
        self.assertNotIn("SUPABASE_SERVICE_ROLE_KEY", context_module)
        self.assertNotIn("IROS_SUPABASE_SECRET_KEY", context_module)

    def test_phase2_ui_exposes_formula_source_period_and_feed_gate(self) -> None:
        page = Path("apps/dashboard/app/page.tsx").read_text()

        self.assertIn("metric.formula", page)
        self.assertIn("metric.sourcePeriod", page)
        self.assertIn("Licensed feed required", page)
        self.assertIn("Open issuer release", page)
        self.assertIn("Source-backed risk", page)
        self.assertIn("Monitor RXRX", page)

    def test_watchlist_write_is_operator_scoped(self) -> None:
        actions = Path("apps/dashboard/app/actions.ts").read_text()
        watchlist = Path("apps/dashboard/lib/watchlist.ts").read_text()

        self.assertIn('from("iros_watchlist_items")', actions)
        self.assertIn('.eq("operator_id", operatorId)', actions)
        self.assertIn('from("iros_watchlist_items")', watchlist)
        self.assertNotIn("SUPABASE_SERVICE_ROLE_KEY", actions + watchlist)
        self.assertNotIn("IROS_SUPABASE_SECRET_KEY", actions + watchlist)

    def test_auth_callback_rejects_cross_origin_redirects(self) -> None:
        callback_route = Path(
            "apps/dashboard/app/auth/callback/route.ts"
        ).read_text()

        self.assertIn("target.origin === origin", callback_route)


if __name__ == "__main__":
    unittest.main()
