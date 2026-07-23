import assert from "node:assert/strict";
import test from "node:test";

import { mapHoldingRows } from "./holdings.ts";

test("maps one complete owner view snapshot in canonical ordinal order", () => {
  const snapshot = mapHoldingRows([
    {
      snapshot_id: "11111111-1111-4111-8111-111111111111",
      portfolio_key: "primary-brokerage",
      account_label: "Primary brokerage",
      currency: null,
      currency_state: "indeterminate",
      observed_at: null,
      timing_state: "indeterminate",
      observation_time_text: "16:00; date and timezone absent",
      source_type: "user_supplied_screenshot",
      source_sha256: "a".repeat(64),
      captured_at: "2026-07-22T08:00:00+00:00",
      content_sha256: "b".repeat(64),
      expected_position_count: 1,
      total_market_value: "19.00",
      total_cost_basis: "20.00",
      total_unrealized_pnl: "-1.00",
      position_id: "22222222-2222-4222-8222-222222222222",
      security_id: "33333333-3333-4333-8333-333333333333",
      ordinal: 1,
      symbol_observed: "ALFA",
      quantity: "2",
      average_cost: "10.00",
      observed_price: "9.50",
      observed_market_value: "19.00",
      cost_basis: "20.00",
      unrealized_pnl: "-1.00",
    },
  ]);

  assert.equal(snapshot?.currency, null);
  assert.equal(snapshot?.positions[0].ticker, "ALFA");
  assert.equal(snapshot?.positions[0].unrealizedPnl, -1);
});
