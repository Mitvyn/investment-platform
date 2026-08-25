import assert from "node:assert/strict";
import test from "node:test";

import {
  isQuantErrorCode,
  parseQuantDatasetStatus,
  parseQuantLocalResult,
  type QuantLocalResult,
} from "./quant-workspace.ts";

const SECURITY_ID = "6f1d2c3b-4a5e-4f6a-8b9c-0d1e2f3a4b5c";
const HASH = "a".repeat(64);

function datasetReceipt() {
  return {
    as_of_cutoff: "2026-01-20",
    corporate_actions_sha256: HASH,
    currency: "USD",
    dataset_sha256: HASH,
    first_session: "2025-01-06",
    interval: "1d",
    last_session: "2026-01-20",
    price_basis: "unadjusted",
    series_sha256: HASH,
    session_count: 80,
    source_content_sha256: HASH,
    source_id: "operator_local_csv",
    source_revision: "2026-01-20-eod",
    split_count: 0,
  };
}

function outcome(overrides: Record<string, unknown> = {}) {
  return {
    backtest_sha256: HASH,
    commission: "12.00",
    constrained_decisions: 0,
    cost_total: "30.00",
    final_equity: "101000.00",
    max_drawdown: "0.020000",
    return_observations: 79,
    sharpe_ratio: "1.100000",
    slippage: "10.00",
    strategy_config_sha256: HASH,
    strategy_id: "trend_following_sma.v1",
    total_return: "0.010000",
    trade_count: 4,
    transaction_cost: "8.00",
    unfilled_shares: 0,
    volatility: "0.004000",
    zero_fill_decisions: 0,
    ...overrides,
  };
}

function result(overrides: Record<string, unknown> = {}) {
  return {
    as_of_cutoff: "2026-01-20",
    assumptions: { lookback_sessions: 5, starting_cash: "100000.00" },
    benchmark: outcome({ strategy_id: "buy-and-hold" }),
    content_sha256: HASH,
    contract_version: "quant_local_result.v1",
    corporate_actions_sha256: HASH,
    currency: "USD",
    dataset_sha256: HASH,
    excess_return: "-0.004000",
    first_session: "2025-01-06",
    last_session: "2026-01-20",
    limitations: ["historical_analysis_not_prediction"],
    security_id: SECURITY_ID,
    series_sha256: HASH,
    session_count: 80,
    source_content_sha256: HASH,
    source_id: "operator_local_csv",
    source_revision: "2026-01-20-eod",
    split_count: 0,
    strategy: outcome(),
    validation: {
      alpha_effective: "0.025000",
      alpha_label: "0.05",
      baseline_scenario_label: "declared",
      degrees_of_freedom: 4,
      degrees_of_freedom_bucket: null,
      first_failing_scenario_label: "stressed",
      gaps: ["overlapping_test_windows"],
      highest_passing_scenario_label: null,
      outcome: "inconclusive",
      reason_codes: [],
      report_sha256: HASH,
      scenarios: [
        {
          aggregate_excess: "-0.010000",
          critical_value: null,
          label: "declared",
          mean_excess: "-0.002000",
          passed: false,
          t_statistic: null,
          windows_beating_benchmark: 1,
        },
      ],
      test_windows_overlap: true,
      window_count: 5,
      windows_beating_benchmark: 1,
    },
    ...overrides,
  };
}

test("parses a dataset status carrying an active receipt", () => {
  const parsed = parseQuantDatasetStatus({
    contract_version: "quant_local_dataset_receipt.v1",
    dataset: datasetReceipt(),
    security_id: SECURITY_ID,
  });

  assert.equal(parsed?.dataset?.session_count, 80);
  assert.equal(parsed?.dataset?.interval, "1d");
  assert.equal(parsed?.security_id, SECURITY_ID);
});

test("parses an explicit absence of a dataset", () => {
  const parsed = parseQuantDatasetStatus({
    contract_version: "quant_local_dataset_receipt.v1",
    dataset: null,
    security_id: SECURITY_ID,
  });

  assert.equal(parsed?.dataset, null);
});

test("rejects a dataset status on a different contract version", () => {
  assert.equal(
    parseQuantDatasetStatus({
      contract_version: "quant_local_dataset_receipt.v2",
      dataset: null,
      security_id: SECURITY_ID,
    }),
    null,
  );
});

test("rejects an adjusted or intraday dataset receipt", () => {
  for (const override of [{ price_basis: "adjusted" }, { interval: "1m" }]) {
    assert.equal(
      parseQuantDatasetStatus({
        contract_version: "quant_local_dataset_receipt.v1",
        dataset: { ...datasetReceipt(), ...override },
        security_id: SECURITY_ID,
      }),
      null,
    );
  }
});

test("parses a complete local result", () => {
  const parsed: QuantLocalResult | null = parseQuantLocalResult(result());

  assert.equal(parsed?.strategy.strategy_id, "trend_following_sma.v1");
  assert.equal(parsed?.benchmark.strategy_id, "buy-and-hold");
  assert.equal(parsed?.validation.outcome, "inconclusive");
  assert.deepEqual(parsed?.validation.gaps, ["overlapping_test_windows"]);
});

test("accepts unmeasurable dispersion as an explicit null", () => {
  const parsed = parseQuantLocalResult(
    result({ strategy: outcome({ sharpe_ratio: null, volatility: null }) }),
  );

  assert.equal(parsed?.strategy.volatility, null);
  assert.equal(parsed?.strategy.sharpe_ratio, null);
});

test("rejects a result missing its benchmark or validation", () => {
  for (const override of [{ benchmark: undefined }, { validation: undefined }]) {
    assert.equal(parseQuantLocalResult({ ...result(), ...override }), null);
  }
});

test("rejects a result whose returns are numbers rather than decimal text", () => {
  assert.equal(
    parseQuantLocalResult(result({ strategy: outcome({ total_return: 0.01 }) })),
    null,
  );
});

test("rejects a result carrying another bounded context's fields", () => {
  for (const override of [
    { holdings: [] },
    { thesis: { id: "x" } },
    { assumptions: { position_size: "10" } },
    { validation: { ...result().validation, recommendation: "buy" } },
  ]) {
    assert.equal(parseQuantLocalResult({ ...result(), ...override }), null);
  }
});

test("rejects a dataset status carrying portfolio state", () => {
  assert.equal(
    parseQuantDatasetStatus({
      contract_version: "quant_local_dataset_receipt.v1",
      dataset: datasetReceipt(),
      positions: [],
      security_id: SECURITY_ID,
    }),
    null,
  );
});

test("rejects a result with an unknown validation outcome", () => {
  assert.equal(
    parseQuantLocalResult(
      result({ validation: { ...result().validation, outcome: "profitable" } }),
    ),
    null,
  );
});

test("recognises every provider-fetch error code as reviewed", () => {
  for (const code of [
    "fetch_provider_blocked",
    "fetch_provider_rejected",
    "fetch_provider_unavailable",
    "fetch_ticker_invalid",
    "fetch_window_invalid",
  ]) {
    assert.equal(isQuantErrorCode(code), true);
  }
  assert.equal(isQuantErrorCode("fetch_made_up_code"), false);
});
