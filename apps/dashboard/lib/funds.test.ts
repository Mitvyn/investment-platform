import assert from "node:assert/strict";
import test from "node:test";

import {
  type FundRow,
  resolveFundKey,
  summarizeFunds,
} from "./funds.ts";

function row(overrides: Partial<FundRow> = {}): FundRow {
  return {
    portfolio_key: "primary-brokerage",
    account_label: "Primary brokerage",
    currency: "USD",
    currency_state: "declared",
    captured_at: "2026-08-13T12:00:00Z",
    expected_position_count: 5,
    total_market_value: "1023.03",
    total_cost_basis: "1090.25",
    total_unrealized_pnl: "-67.22",
    ...overrides,
  };
}

test("summarizes one fund per portfolio key and totals them exactly", () => {
  const { funds, total } = summarizeFunds([
    row(),
    row({
      portfolio_key: "speculative",
      account_label: "Speculative",
      total_market_value: "4880.10",
      total_cost_basis: "4860.00",
      total_unrealized_pnl: "20.10",
      expected_position_count: 2,
    }),
  ]);

  assert.deepEqual(
    funds.map((fund) => fund.fundKey),
    ["primary-brokerage", "speculative"],
  );
  assert.equal(total?.marketValue, "5903.13");
  assert.equal(total?.costBasis, "5950.25");
  assert.equal(total?.unrealizedPnl, "-47.12");
  assert.equal(total?.mixedCurrency, false);
});

test("keeps cross-fund totals exact where float addition would drift", () => {
  const { total } = summarizeFunds([
    row({ portfolio_key: "a", total_market_value: "0.10", total_cost_basis: "0.10", total_unrealized_pnl: "0.00" }),
    row({ portfolio_key: "b", total_market_value: "0.20", total_cost_basis: "0.20", total_unrealized_pnl: "0.00" }),
  ]);
  // 0.1 + 0.2 === 0.30000000000000004 in IEEE-754.
  assert.equal(total?.marketValue, "0.30");
});

test("withholds a total when funds disagree on currency", () => {
  const { total } = summarizeFunds([
    row({ portfolio_key: "usd-fund", currency: "USD" }),
    row({ portfolio_key: "sgd-fund", currency: "SGD" }),
  ]);
  assert.equal(total?.mixedCurrency, true);
  assert.equal(total?.currencyLabel, "Mixed currencies");
});

test("treats an undeclared currency as its own group and never claims one", () => {
  const { funds } = summarizeFunds([
    row({ currency: null, currency_state: "indeterminate" }),
  ]);
  assert.equal(funds[0].currency, null);
  assert.equal(funds[0].currencyLabel, "Currency unspecified");
});

test("keeps only the newest row per fund", () => {
  const { funds } = summarizeFunds([
    row({ total_market_value: "100.00" }),
    row({ total_market_value: "999.00" }),
  ]);
  assert.equal(funds.length, 1);
  assert.equal(funds[0].marketValue, "100.00");
});

test("reports no percentage when cost basis is zero rather than dividing", () => {
  const { funds, total } = summarizeFunds([
    row({ total_cost_basis: "0.00", total_unrealized_pnl: "0.00" }),
  ]);
  assert.equal(funds[0].unrealizedPnlPercent, null);
  assert.equal(total?.unrealizedPnlPercent, null);
});

test("labels a fund from its key when no account label is stored", () => {
  const { funds } = summarizeFunds([
    row({ portfolio_key: "moomoo-sg", account_label: "  " }),
  ]);
  assert.equal(funds[0].label, "Moomoo Sg");
});

test("resolves the requested fund, falling back without throwing", () => {
  const { funds } = summarizeFunds([
    row({ portfolio_key: "speculative" }),
    row(),
  ]);
  assert.equal(resolveFundKey("speculative", funds), "speculative");
  assert.equal(resolveFundKey("SPECULATIVE", funds), "speculative");
  assert.equal(resolveFundKey("does-not-exist", funds), "primary-brokerage");
  assert.equal(resolveFundKey(undefined, funds), "primary-brokerage");
  assert.equal(resolveFundKey("anything", []), null);
});

test("rejects a malformed total rather than silently coercing it", () => {
  assert.throws(
    () => summarizeFunds([row({ total_market_value: "1,023.03" })]),
    /exact decimal/,
  );
});
