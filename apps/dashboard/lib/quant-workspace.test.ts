import assert from "node:assert/strict";
import test from "node:test";

import type { QuantDatasetReceipt, QuantLocalResult } from "@iros/types";

import {
  buildQuantWorkspaceView,
  quantErrorCodeFromQuery,
  quantErrorMessage,
  quantGapMessage,
  quantLimitationMessage,
} from "./quant-workspace.ts";

const HASH = "a".repeat(64);
const SECURITY_ID = "6f1d2c3b-4a5e-4f6a-8b9c-0d1e2f3a4b5c";

function dataset(): QuantDatasetReceipt {
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
    split_count: 1,
  };
}

function outcome(overrides: Record<string, unknown> = {}) {
  return {
    backtest_sha256: HASH,
    commission: "12.00",
    constrained_decisions: 1,
    cost_total: "30.00",
    final_equity: "101000.00",
    max_drawdown: "0.025000",
    return_observations: 79,
    sharpe_ratio: "1.100000",
    slippage: "10.00",
    strategy_config_sha256: HASH,
    strategy_id: "trend_following_sma.v1",
    total_return: "0.010000",
    trade_count: 4,
    transaction_cost: "8.00",
    unfilled_shares: 25,
    volatility: "0.004000",
    zero_fill_decisions: 0,
    ...overrides,
  } as QuantLocalResult["strategy"];
}

function result(overrides: Record<string, unknown> = {}): QuantLocalResult {
  return {
    as_of_cutoff: "2026-01-20",
    assumptions: { lookback_sessions: 5, starting_cash: "100000.00" },
    benchmark: outcome({
      strategy_id: "buy-and-hold",
      total_return: "0.050000",
      trade_count: 1,
    }),
    content_sha256: HASH,
    contract_version: "quant_local_result.v1",
    corporate_actions_sha256: HASH,
    currency: "USD",
    dataset_sha256: HASH,
    excess_return: "-0.040000",
    first_session: "2025-01-06",
    last_session: "2026-01-20",
    limitations: ["historical_analysis_not_prediction", "no_dividends_modelled"],
    security_id: SECURITY_ID,
    series_sha256: HASH,
    session_count: 80,
    source_content_sha256: HASH,
    source_id: "operator_local_csv",
    source_revision: "2026-01-20-eod",
    split_count: 1,
    strategy: outcome(),
    validation: {
      alpha_effective: "0.025000",
      alpha_label: "0.05",
      baseline_scenario_label: "declared",
      degrees_of_freedom: 4,
      degrees_of_freedom_bucket: null,
      first_failing_scenario_label: "stressed",
      gaps: ["overlapping_test_windows", "benchmark_unreachable"],
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
  } as QuantLocalResult;
}

test("reports the desktop workspace as unavailable when the worker is not running", () => {
  const view = buildQuantWorkspaceView({
    dataset: null,
    errorCode: null,
    result: null,
    workspaceAvailable: false,
  });

  assert.equal(view.state, "unavailable");
  assert.match(view.headline, /desktop/i);
});

test("asks for a dataset import before any analysis is possible", () => {
  const view = buildQuantWorkspaceView({
    dataset: null,
    errorCode: null,
    result: null,
    workspaceAvailable: true,
  });

  assert.equal(view.state, "no_dataset");
  assert.equal(view.canRun, false);
  assert.match(view.headline, /dataset/i);
});

test("an imported dataset enables a run and shows its cutoff and provenance", () => {
  const view = buildQuantWorkspaceView({
    dataset: dataset(),
    errorCode: null,
    result: null,
    workspaceAvailable: true,
  });

  assert.equal(view.state, "dataset_ready");
  assert.equal(view.canRun, true);
  assert.equal(view.datasetSummary?.cutoff, "2026-01-20");
  assert.equal(view.datasetSummary?.sessionCount, 80);
  assert.equal(view.datasetSummary?.sourceRevision, "2026-01-20-eod");
});

test("a completed run reports return, drawdown, volatility, trades, unfilled shares and costs", () => {
  const view = buildQuantWorkspaceView({
    dataset: dataset(),
    errorCode: null,
    result: result(),
    workspaceAvailable: true,
  });

  assert.equal(view.state, "result_ready");
  const labels = view.metrics.map((metric) => metric.label);
  for (const label of [
    "Total return",
    "Maximum drawdown",
    "Volatility",
    "Trades",
    "Unfilled shares",
    "Cost impact",
  ]) {
    assert.ok(labels.includes(label), `${label} is missing`);
  }
  for (const metric of view.metrics) {
    assert.ok(metric.plainLanguage.length > 20, `${metric.label} has no explanation`);
  }
});

test("every metric is explained without predictive or advisory language", () => {
  const view = buildQuantWorkspaceView({
    dataset: dataset(),
    errorCode: null,
    result: result(),
    workspaceAvailable: true,
  });

  for (const metric of view.metrics) {
    assert.doesNotMatch(
      metric.plainLanguage,
      /\b(buy|sell|should invest|will return|expected to|recommend)\b/i,
    );
  }
  assert.match(view.disclaimer, /historical/i);
  assert.doesNotMatch(view.disclaimer, /prediction of|recommendation to/i);
});

test("the benchmark comparison names buy and hold and states who was ahead", () => {
  const view = buildQuantWorkspaceView({
    dataset: dataset(),
    errorCode: null,
    result: result(),
    workspaceAvailable: true,
  });

  assert.match(view.benchmark?.label ?? "", /buy and hold/i);
  assert.equal(view.benchmark?.strategyAhead, false);
  assert.equal(view.benchmark?.excessReturn, "-0.040000");
});

test("walk-forward counts and gaps are surfaced in plain language", () => {
  const view = buildQuantWorkspaceView({
    dataset: dataset(),
    errorCode: null,
    result: result(),
    workspaceAvailable: true,
  });

  assert.equal(view.validation?.windowCount, 5);
  assert.equal(view.validation?.windowsBeatingBenchmark, 1);
  assert.equal(view.validation?.gaps.length, 2);
  for (const gap of view.validation?.gaps ?? []) {
    assert.ok(gap.explanation.length > 20);
  }
});

test("an insufficient-data run never presents a verdict as a result", () => {
  const view = buildQuantWorkspaceView({
    dataset: dataset(),
    errorCode: null,
    result: result({
      validation: {
        ...result().validation,
        gaps: ["insufficient_windows"],
        outcome: "insufficient_data",
        reason_codes: ["too_few_windows"],
        scenarios: [],
        window_count: 1,
      },
    }),
    workspaceAvailable: true,
  });

  assert.equal(view.state, "result_ready");
  assert.match(view.validation?.headline ?? "", /not enough/i);
  assert.equal(view.validation?.validated, false);
});

test("collapsed detail carries source, cutoff, hashes, strategy config and limitations", () => {
  const view = buildQuantWorkspaceView({
    dataset: dataset(),
    errorCode: null,
    result: result(),
    workspaceAvailable: true,
  });

  const labels = view.detail.map((entry) => entry.label);
  for (const label of [
    "Source",
    "Source revision",
    "As-of cutoff",
    "Dataset hash",
    "Result hash",
    "Strategy",
    "Strategy configuration hash",
  ]) {
    assert.ok(labels.includes(label), `${label} is missing from detail`);
  }
  assert.equal(view.limitations.length, 2);
  for (const limitation of view.limitations) {
    assert.ok(limitation.length > 20);
  }
});

test("an error code is shown as plain language instead of a raw code", () => {
  const view = buildQuantWorkspaceView({
    dataset: null,
    errorCode: "dataset_future_data",
    result: null,
    workspaceAvailable: true,
  });

  assert.equal(view.state, "no_dataset");
  assert.match(view.errorMessage ?? "", /after/i);
  assert.doesNotMatch(view.errorMessage ?? "", /dataset_future_data/);
});

test("every known worker code has plain language and an unknown one still does", () => {
  for (const code of [
    "dataset_contract_invalid",
    "dataset_currency_invalid",
    "dataset_cutoff_invalid",
    "dataset_file_unreadable",
    "dataset_future_data",
    "dataset_hash_mismatch",
    "dataset_path_invalid",
    "dataset_rows_invalid",
    "dataset_security_mismatch",
    "dataset_sessions_invalid",
    "dataset_split_uncovered",
    "dataset_too_large",
    "run_assumptions_invalid",
    "run_dataset_invalid",
    "run_dataset_missing",
    "quant_workspace_unavailable",
    "surprising_new_code",
  ]) {
    const message = quantErrorMessage(code);
    assert.ok(message.length > 15, `${code} has no message`);
    assert.doesNotMatch(message, /_/);
  }
});

test("gap and limitation codes are never shown raw", () => {
  for (const code of [
    "insufficient_windows",
    "overlapping_test_windows",
    "benchmark_unreachable",
    "below_smallest_significance_sample",
    "alpha_outside_critical_value_table",
    "dispersion_unmeasurable",
    "fails_under_higher_costs",
    "unknown_future_gap",
  ]) {
    assert.doesNotMatch(quantGapMessage(code), /_/);
  }
  for (const code of [
    "historical_analysis_not_prediction",
    "single_security_no_universe",
    "operator_declared_provenance",
    "split_adjusted_closes_only",
    "no_dividends_modelled",
    "declared_trials_unverifiable",
    "unknown_future_limitation",
  ]) {
    assert.doesNotMatch(quantLimitationMessage(code), /_/);
  }
});

test("the workspace stays usable with no holdings and never mentions any", () => {
  const view = buildQuantWorkspaceView({
    dataset: dataset(),
    errorCode: null,
    result: result(),
    workspaceAvailable: true,
  });

  // Data, not prose: the disclaimer deliberately says this is not evidence for
  // a research thesis, and that sentence is the point rather than a leak. What
  // must never appear is a value or a label carrying another domain's state.
  const data = JSON.stringify([
    view.benchmark?.benchmarkReturn,
    view.benchmark?.excessReturn,
    view.benchmark?.strategyReturn,
    view.datasetSummary,
    view.detail,
    view.metrics.map((metric) => [metric.label, metric.value]),
    view.validation?.windowCount,
    view.validation?.windowsBeatingBenchmark,
  ]).toLowerCase();
  for (const forbidden of [
    "holding",
    "position",
    "portfolio",
    "broker",
    "allocation",
    "thesis",
    "evidence",
  ]) {
    assert.equal(
      data.includes(forbidden),
      false,
      `${forbidden} leaked into the Quant view`,
    );
  }
  assert.equal(view.canRun, true);
});

test("an absent error query parameter produces no error state", () => {
  for (const value of [undefined, null, ""]) {
    assert.equal(quantErrorCodeFromQuery(value), null);
  }
});

test("a reviewed error code from the query is kept", () => {
  assert.equal(
    quantErrorCodeFromQuery("dataset_future_data"),
    "dataset_future_data",
  );
});

test("an unreviewed error code from the query never reaches the page", () => {
  // The query string is attacker-supplied. Without this, any text could be
  // rendered into the workspace by handing someone a crafted link.
  for (const value of [
    "your account has been suspended, call 555 0100",
    "<script>alert(1)</script>",
    "dataset_future_data extra",
    "a".repeat(500),
    42,
    { code: "dataset_future_data" },
  ]) {
    assert.equal(quantErrorCodeFromQuery(value), "quant_request_invalid");
  }
});

test("a crafted error query renders only the generic refusal", () => {
  const view = buildQuantWorkspaceView({
    dataset: null,
    errorCode: quantErrorCodeFromQuery("call 555 0100 to restore your account"),
    result: null,
    workspaceAvailable: true,
  });

  assert.equal(view.errorMessage, quantErrorMessage("quant_request_invalid"));
  assert.doesNotMatch(view.errorMessage ?? "", /555|account/i);
});
