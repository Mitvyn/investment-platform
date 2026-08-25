import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("../components/quant-panel.tsx", import.meta.url),
  "utf8",
);

test("the quant panel is a working workspace rather than a placeholder", () => {
  assert.doesNotMatch(source, /Not yet available/);
  assert.doesNotMatch(source, /Paper signals/);
  for (const label of [
    "Import dataset",
    "Run analysis",
    "Dataset",
    "Assumptions",
    "Benchmark",
    "Walk-forward validation",
    "What this cannot tell you",
    "Provenance and configuration",
  ]) {
    assert.match(source, new RegExp(label), `${label} is missing`);
  }
});

test("the panel drives both server actions and carries the security identity", () => {
  assert.match(source, /importQuantDatasetAction/);
  assert.match(source, /runQuantAnalysisAction/);
  assert.match(source, /name="securityId"/);
  assert.match(source, /name="datasetPath"/);
});

test("every declared assumption is an explicit form field", () => {
  for (const field of [
    "starting_cash",
    "commission_per_share",
    "commission_bps",
    "commission_minimum",
    "transaction_cost_bps",
    "slippage_bps",
    "max_participation_bps",
    "min_fill_shares",
    "lookback_sessions",
    "train_sessions",
    "test_sessions",
    "step_sessions",
    "embargo_sessions",
    "min_windows",
    "min_trades_per_window",
    "min_total_trades",
    "annualisation_periods",
    "alpha",
    "cost_stress_multiplier",
    "trials_declared",
  ]) {
    assert.match(
      source,
      new RegExp(`name: "${field}"|name="${field}"`),
      `${field} is not declared`,
    );
  }
});

test("the panel renders result, unavailable, and error states from the view", () => {
  // The four workspace states are decided in `quant-workspace.ts` and tested
  // there. What the panel owns is refusing to offer actions it cannot perform
  // and showing a failure when one arrives.
  assert.match(source, /"result_ready"/);
  assert.match(source, /"unavailable"/);
  assert.match(source, /errorMessage/);
  assert.match(source, /disabled=\{!view\.canRun\}/);
  assert.match(source, /disabled=\{!canImport\}/);
});

test("the panel presents no trading, holdings, or advisory surface", () => {
  assert.doesNotMatch(
    source,
    /place order|submit order|paper trade|position size|allocate|rebalance now/i,
  );
  // "Broker charge" names a cost input and nothing else: no account, holding,
  // or connection state may appear on this surface.
  assert.doesNotMatch(source, /holdings|portfolio|thesis|evidence bundle/i);
  assert.doesNotMatch(source, /broker (account|connection|state)/i);
  assert.match(source, /historical analysis/i);
});

test("the panel explains metrics and shows provenance in collapsed detail", () => {
  assert.match(source, /plainLanguage/);
  assert.match(source, /<details/);
  assert.match(source, /limitations/);
  assert.match(source, /disclaimer/);
});
