import assert from "node:assert/strict";
import test from "node:test";

import { mapPortfolioMirrorRows } from "./portfolio-mirror.ts";

const row: Parameters<typeof mapPortfolioMirrorRows>[0][number] = {
  account_id: "33333333-3333-4333-8333-333333333333",
  provider: "moomoo_rest",
  provider_transport: "web_rest_oauth",
  snapshot_id: "44444444-4444-4444-8444-444444444444",
  content_sha256: "a".repeat(64),
  captured_at: "2026-08-12T09:30:00+00:00",
  checked_at: "2026-08-12T09:30:00+00:00",
  expected_position_count: 1,
  unmapped_count: 0,
  ambiguous_count: 0,
  precision_risk_count: 0,
  read_only_assurance: "read_only_scopes_no_order_surface",
  position_id: "55555555-5555-4555-8555-555555555555",
  ordinal: 1,
  provider_symbol: "US.GANX",
  display_name: "Gain Therapeutics",
  canonical_ticker: "GANX",
  security_id: "22222222-2222-4222-8222-222222222222",
  mapping_state: "mapped",
  primary_listing_exchange: "NASDAQ",
  position_side: "LONG",
  quantity_text: "100.0000",
  available_quantity_text: "100.0000",
  average_cost_text: "1.7200",
  average_cost_state: "reported",
  last_price_text: "1.8400",
  market_value_text: "184.0000",
  currency: "USD",
  unrealized_pnl_text: "12.0000",
  unrealized_pnl_state: "reported",
  precision_risk_fields: [],
};

test("maps persisted portfolio rows without converting decimal strings", () => {
  const holdings = mapPortfolioMirrorRows([row]);

  assert.equal(holdings?.source, "hosted_snapshot");
  assert.equal(holdings?.positions[0].quantity, "100.0000");
  assert.equal(holdings?.positions[0].marketValue, "184.0000");
  assert.equal(holdings?.positions[0].mappingState, "mapped");
  assert.equal(holdings?.positions[0].canonicalTicker, "GANX");
});

test("rejects incomplete immutable snapshot rows", () => {
  assert.throws(
    () => mapPortfolioMirrorRows([{ ...row, expected_position_count: 2 }]),
    /inconsistent immutable snapshot/,
  );
});
