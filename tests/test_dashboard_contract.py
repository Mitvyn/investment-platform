from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


class DashboardContractTests(unittest.TestCase):
    def test_fixture_preserves_exact_sec_trace(self) -> None:
        fixture = json.loads(Path("apps/dashboard/data/rxrx-trace.json").read_text())

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
        dashboard_text = "\n".join(path.read_text() for path in source_paths).lower()

        forbidden = "service" + "_role"
        self.assertNotIn(forbidden, dashboard_text)
        self.assertIn("@supabase/ssr", dashboard_text)
        self.assertIn("getclaims", dashboard_text)
        self.assertNotIn("iros_access_token", dashboard_text)
        self.assertIn("shouldcreateuser: false", dashboard_text)

    def test_runtime_evidence_path_does_not_fall_back_to_fixture(self) -> None:
        evidence_module = Path("apps/dashboard/lib/evidence.ts").read_text()

        self.assertIn(
            'from("iros_v_security_claim_evidence_trace")', evidence_module
        )
        self.assertNotIn("rxrx-trace.json", evidence_module)

    def test_phase2_context_uses_authenticated_security_invoker_views(self) -> None:
        context_module = Path("apps/dashboard/lib/context.ts").read_text()

        self.assertIn('from("iros_v_security_financial_health")', context_module)
        self.assertIn('from("iros_v_security_catalyst_context")', context_module)
        self.assertIn('from("iros_v_security_market_context")', context_module)
        self.assertIn('from("iros_v_security_risk_context")', context_module)
        self.assertNotIn("TWELVE_DATA_API_KEY", context_module)
        self.assertNotIn("SUPABASE_SERVICE_ROLE_KEY", context_module)
        self.assertNotIn("IROS_SUPABASE_SECRET_KEY", context_module)

    def test_legacy_evidence_context_loaders_are_stable_security_scoped(self) -> None:
        evidence_module = Path("apps/dashboard/lib/evidence.ts").read_text()
        context_module = Path("apps/dashboard/lib/context.ts").read_text()

        self.assertIn(
            'from("iros_v_security_claim_evidence_trace")', evidence_module
        )
        self.assertIn('.eq("security_id", securityId)', evidence_module)
        for view_name in (
            "iros_v_security_financial_health",
            "iros_v_security_catalyst_context",
            "iros_v_security_risk_context",
            "iros_v_security_market_context",
        ):
            self.assertIn(f'from("{view_name}")', context_module)
        self.assertGreaterEqual(
            context_module.count('.eq("security_id", securityId)'), 5
        )
        self.assertNotIn('.eq("ticker", normalizedTicker)', context_module)

    def test_phase2_ui_labels_personal_yfinance_feed_explicitly(self) -> None:
        page = Path("apps/dashboard/app/page.tsx").read_text()

        self.assertIn("metric.formula", page)
        self.assertIn("metric.sourcePeriod", page)
        self.assertIn("Personal-use feed unavailable", page)
        self.assertIn("unofficial personal-use data", page)
        self.assertIn("dashboard never calls Yahoo Finance directly", page)
        self.assertIn("Open issuer release", page)
        self.assertIn("Source-backed risk", page)
        self.assertIn("Monitor ${ticker}", page)

    def test_watchlist_write_is_operator_scoped(self) -> None:
        actions = Path("apps/dashboard/app/actions.ts").read_text()
        watchlist = Path("apps/dashboard/lib/watchlist.ts").read_text()

        self.assertIn('from("iros_watchlist_items")', actions)
        self.assertIn('from("iros_securities")', actions)
        self.assertIn('.eq("operator_id", operatorId)', actions)
        self.assertIn("issuer_name", actions)
        self.assertNotIn('formData.get("ticker")', actions)
        self.assertNotIn('formData.get("companyName")', actions)
        self.assertIn('from("iros_watchlist_items")', watchlist)
        self.assertIn('is("security_id", null)', actions)
        self.assertIn('.in("id", watchlistIds)', actions)
        self.assertNotIn("SUPABASE_SERVICE_ROLE_KEY", actions + watchlist)
        self.assertNotIn("IROS_SUPABASE_SECRET_KEY", actions + watchlist)

    def test_ticker_workspace_is_stable_security_driven_and_renders_ohlcv(self) -> None:
        page = Path("apps/dashboard/app/page.tsx").read_text()
        actions = Path("apps/dashboard/app/actions.ts").read_text()
        context = Path("apps/dashboard/lib/context.ts").read_text()
        chart = Path("apps/dashboard/components/market-price-chart.tsx").read_text()

        self.assertIn("loadSecurityDirectory", page)
        self.assertIn('name="security"', page)
        self.assertIn("loadMarketSeries", page)
        self.assertIn("MarketPriceChart", page)
        self.assertIn("summary.latest.open", page)
        self.assertIn("summary.latest.high", page)
        self.assertIn("summary.latest.low", page)
        self.assertIn("summary.latest.volume", page)
        self.assertIn('from("iros_v_market_series")', context)
        self.assertIn("CandlestickSeries", chart)
        self.assertIn("HistogramSeries", chart)
        self.assertIn("toggleWatchlist", actions)
        self.assertNotIn("toggleRxrxWatchlist", actions)
        self.assertNotIn('.eq("ticker", "RXRX")', actions)
        self.assertNotIn('=== "RXRX"', page)
        self.assertNotIn("item.ticker === ticker", page)

    def test_registered_security_select_uses_padded_custom_indicator(self) -> None:
        page = Path("apps/dashboard/app/page.tsx").read_text()

        self.assertIn("ChevronDown", page)
        self.assertIn("appearance-none", page)
        self.assertIn("pr-10", page)
        self.assertIn("pointer-events-none absolute right-3", page)

    def test_registered_security_indicator_container_matches_control_height(self) -> None:
        page = Path("apps/dashboard/app/page.tsx").read_text()

        self.assertIn('className="relative h-9 min-w-0 flex-1"', page)
        self.assertIn('className="block h-9 w-full appearance-none', page)

    def test_private_holdings_are_visible_without_research_or_trading_authority(
        self,
    ) -> None:
        page = Path("apps/dashboard/app/page.tsx").read_text()
        loader = Path("apps/dashboard/lib/holdings.ts").read_text()
        table = Path("apps/dashboard/components/holdings-table.tsx").read_text()

        self.assertIn("loadLatestHoldings", page)
        self.assertIn("HoldingsTable", page)
        self.assertIn('from("iros_v_latest_holdings")', loader)
        self.assertIn("Operator-entered holdings", table)
        self.assertIn("timing", table.lower())
        self.assertNotIn("target price", table.lower())
        self.assertNotIn("position size", table.lower())
        self.assertNotIn("buy", table.lower())
        self.assertNotIn("sell", table.lower())

    def test_auth_uses_six_digit_email_otp_without_magic_callback(self) -> None:
        actions = Path("apps/dashboard/app/login/actions.ts").read_text()
        page = Path("apps/dashboard/app/login/page.tsx").read_text()

        self.assertIn("verifyOperatorOtp", actions)
        self.assertIn("requestEmailOtp", actions)
        self.assertNotIn("emailRedirectTo", actions)
        self.assertIn('autoComplete="one-time-code"', page)
        self.assertIn('inputMode="numeric"', page)
        self.assertFalse(Path("apps/dashboard/app/auth/callback/route.ts").exists())


if __name__ == "__main__":
    unittest.main()
