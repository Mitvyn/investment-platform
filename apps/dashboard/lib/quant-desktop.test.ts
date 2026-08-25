import assert from "node:assert/strict";
import test from "node:test";

import {
  QuantDesktopError,
  fetchQuantDataset,
  importQuantDataset,
  loadLatestQuantResult,
  loadQuantDatasetStatus,
  runQuantAnalysis,
} from "./quant-desktop.ts";

const OPERATOR_ID = "3b8f1f4a-9d0e-4a51-9d1b-6c2f0b1d51aa";
const SECURITY_ID = "6f1d2c3b-4a5e-4f6a-8b9c-0d1e2f3a4b5c";
const HASH = "a".repeat(64);
const TOKEN = "a".repeat(40);

const READY_ENVIRONMENT = {
  IROS_DESKTOP: "1",
  IROS_DESKTOP_CONTROL_ORIGIN: "http://127.0.0.1:60355",
  IROS_DESKTOP_CONTROL_TOKEN: TOKEN,
  IROS_DESKTOP_WORKER_STATE: "ready",
};

const ASSUMPTIONS = {
  alpha: "0.05",
  annualisation_periods: 252,
  commission_bps: "0",
  commission_minimum: "1.00",
  commission_per_share: "0.01",
  cost_stress_multiplier: "3",
  embargo_sessions: 1,
  lookback_sessions: 5,
  max_participation_bps: "500",
  min_fill_shares: 1,
  min_total_trades: 1,
  min_trades_per_window: 0,
  min_windows: 3,
  slippage_bps: "5",
  starting_cash: "100000.00",
  step_sessions: 10,
  test_sessions: 10,
  train_sessions: 20,
  transaction_cost_bps: "2",
  trials_declared: 2,
};

function datasetStatus(dataset: unknown = null) {
  return {
    contract_version: "quant_local_dataset_receipt.v1",
    dataset,
    security_id: SECURITY_ID,
  };
}

function receipt() {
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

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

function recordingFetch(payload: unknown, status = 200) {
  const calls: Array<{ init: RequestInit | undefined; url: string }> = [];
  const fetcher = async (
    input: string | URL | Request,
    init?: RequestInit,
  ): Promise<Response> => {
    calls.push({ init, url: String(input) });
    return jsonResponse(payload, status);
  };
  return { calls, fetcher };
}

test("dataset status is unavailable when the desktop worker is not ready", async () => {
  for (const environment of [
    {},
    { ...READY_ENVIRONMENT, IROS_DESKTOP: "0" },
    { ...READY_ENVIRONMENT, IROS_DESKTOP_WORKER_STATE: "starting" },
    { ...READY_ENVIRONMENT, IROS_DESKTOP_CONTROL_TOKEN: "short" },
    { ...READY_ENVIRONMENT, IROS_DESKTOP_CONTROL_ORIGIN: "https://example.com" },
  ]) {
    const loaded = await loadQuantDatasetStatus(
      { operatorId: OPERATOR_ID, securityId: SECURITY_ID },
      environment,
      async () => {
        throw new Error("no request may be made without a ready worker");
      },
    );
    assert.equal(loaded.available, false);
    assert.equal(loaded.status, null);
  }
});

test("dataset status is requested from the authenticated loopback worker", async () => {
  const { calls, fetcher } = recordingFetch(datasetStatus(receipt()));

  const loaded = await loadQuantDatasetStatus(
    { operatorId: OPERATOR_ID, securityId: SECURITY_ID },
    READY_ENVIRONMENT,
    fetcher,
  );

  assert.equal(loaded.available, true);
  assert.equal(loaded.status?.dataset?.session_count, 80);
  assert.equal(calls.length, 1);
  assert.match(calls[0].url, /^http:\/\/127\.0\.0\.1:60355\/v1\/quant\/dataset\?/);
  assert.match(calls[0].url, new RegExp(`security_id=${SECURITY_ID}`));
  assert.equal(
    (calls[0].init?.headers as Record<string, string>).Authorization,
    `Bearer ${TOKEN}`,
  );
});

test("an unparsable dataset status is reported as available with no dataset", async () => {
  const { fetcher } = recordingFetch({ contract_version: "something_else" });

  const loaded = await loadQuantDatasetStatus(
    { operatorId: OPERATOR_ID, securityId: SECURITY_ID },
    READY_ENVIRONMENT,
    fetcher,
  );

  assert.equal(loaded.available, true);
  assert.equal(loaded.status, null);
});

test("import posts the operator path and returns the parsed receipt", async () => {
  const { calls, fetcher } = recordingFetch(datasetStatus(receipt()));

  const status = await importQuantDataset(
    {
      datasetPath: "/Users/operator/data/frvo.json",
      operatorId: OPERATOR_ID,
      securityId: SECURITY_ID,
    },
    READY_ENVIRONMENT,
    fetcher,
  );

  assert.equal(status.dataset?.source_id, "operator_local_csv");
  assert.equal(calls[0].url, "http://127.0.0.1:60355/v1/quant/dataset/import");
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
    dataset_path: "/Users/operator/data/frvo.json",
    operator_id: OPERATOR_ID,
    security_id: SECURITY_ID,
  });
});

test("a worker rejection surfaces its reviewed code and nothing else", async () => {
  const { fetcher } = recordingFetch(
    { error: "quant_request_invalid", reason: "dataset_future_data" },
    400,
  );

  await assert.rejects(
    importQuantDataset(
      {
        datasetPath: "/Users/operator/data/frvo.json",
        operatorId: OPERATOR_ID,
        securityId: SECURITY_ID,
      },
      READY_ENVIRONMENT,
      fetcher,
    ),
    (error: unknown) => {
      assert.ok(error instanceof QuantDesktopError);
      assert.equal(error.code, "dataset_future_data");
      return true;
    },
  );
});

test("an unreviewed worker code is normalised rather than passed through", async () => {
  const { fetcher } = recordingFetch(
    { error: "quant_request_invalid", reason: "something the ui never saw" },
    400,
  );

  await assert.rejects(
    importQuantDataset(
      {
        datasetPath: "/Users/operator/data/frvo.json",
        operatorId: OPERATOR_ID,
        securityId: SECURITY_ID,
      },
      READY_ENVIRONMENT,
      fetcher,
    ),
    (error: unknown) => {
      assert.ok(error instanceof QuantDesktopError);
      assert.equal(error.code, "quant_request_invalid");
      return true;
    },
  );
});

test("import refuses a relative path before any request is made", async () => {
  await assert.rejects(
    importQuantDataset(
      {
        datasetPath: "data/frvo.json",
        operatorId: OPERATOR_ID,
        securityId: SECURITY_ID,
      },
      READY_ENVIRONMENT,
      async () => {
        throw new Error("no request may be made for an invalid path");
      },
    ),
    (error: unknown) => {
      assert.ok(error instanceof QuantDesktopError);
      assert.equal(error.code, "dataset_path_invalid");
      return true;
    },
  );
});

test("fetch posts the operator, ticker, and window and returns the parsed receipt", async () => {
  const { calls, fetcher } = recordingFetch(datasetStatus(receipt()));

  const status = await fetchQuantDataset(
    {
      asOfCutoff: "2026-01-20",
      operatorId: OPERATOR_ID,
      securityId: SECURITY_ID,
      start: "2025-01-06",
      ticker: "frvo",
    },
    READY_ENVIRONMENT,
    fetcher,
  );

  assert.equal(status.dataset?.source_id, "operator_local_csv");
  assert.equal(calls[0].url, "http://127.0.0.1:60355/v1/quant/dataset/fetch");
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
    as_of_cutoff: "2026-01-20",
    operator_id: OPERATOR_ID,
    security_id: SECURITY_ID,
    start: "2025-01-06",
    ticker: "frvo",
  });
});

test("fetch refuses a blank ticker before any request is made", async () => {
  await assert.rejects(
    fetchQuantDataset(
      {
        asOfCutoff: "2026-01-20",
        operatorId: OPERATOR_ID,
        securityId: SECURITY_ID,
        start: "2025-01-06",
        ticker: "   ",
      },
      READY_ENVIRONMENT,
      async () => {
        throw new Error("no request may be made for a blank ticker");
      },
    ),
    (error: unknown) => {
      assert.ok(error instanceof QuantDesktopError);
      assert.equal(error.code, "fetch_ticker_invalid");
      return true;
    },
  );
});

test("fetch refuses a non-ISO window date before any request is made", async () => {
  for (const [start, asOfCutoff] of [
    ["01/06/2025", "2026-01-20"],
    ["2025-01-06", "next friday"],
  ]) {
    await assert.rejects(
      fetchQuantDataset(
        {
          asOfCutoff,
          operatorId: OPERATOR_ID,
          securityId: SECURITY_ID,
          start,
          ticker: "FRVO",
        },
        READY_ENVIRONMENT,
        async () => {
          throw new Error("no request may be made for an invalid window");
        },
      ),
      (error: unknown) => {
        assert.ok(error instanceof QuantDesktopError);
        assert.equal(error.code, "fetch_window_invalid");
        return true;
      },
    );
  }
});

test("fetch surfaces the worker's reviewed code on a provider rejection", async () => {
  const { fetcher } = recordingFetch(
    { error: "quant_request_invalid", reason: "fetch_provider_rejected" },
    400,
  );

  await assert.rejects(
    fetchQuantDataset(
      {
        asOfCutoff: "2026-01-20",
        operatorId: OPERATOR_ID,
        securityId: SECURITY_ID,
        start: "2025-01-06",
        ticker: "FRVO",
      },
      READY_ENVIRONMENT,
      fetcher,
    ),
    (error: unknown) => {
      assert.ok(error instanceof QuantDesktopError);
      assert.equal(error.code, "fetch_provider_rejected");
      return true;
    },
  );
});

test("fetch refuses a non-canonical identity before any request", async () => {
  await assert.rejects(
    fetchQuantDataset(
      {
        asOfCutoff: "2026-01-20",
        operatorId: "not-a-uuid",
        securityId: SECURITY_ID,
        start: "2025-01-06",
        ticker: "FRVO",
      },
      READY_ENVIRONMENT,
      async () => {
        throw new Error("no request may be made for an invalid identity");
      },
    ),
    QuantDesktopError,
  );
});

test("import and run refuse a non-canonical identity before any request", async () => {
  const rejecting = async () => {
    throw new Error("no request may be made for an invalid identity");
  };
  for (const identity of ["not-a-uuid", "", "../escape"]) {
    await assert.rejects(
      importQuantDataset(
        {
          datasetPath: "/Users/operator/data/frvo.json",
          operatorId: OPERATOR_ID,
          securityId: identity,
        },
        READY_ENVIRONMENT,
        rejecting,
      ),
      QuantDesktopError,
    );
    await assert.rejects(
      runQuantAnalysis(
        { assumptions: ASSUMPTIONS, operatorId: identity, securityId: SECURITY_ID },
        READY_ENVIRONMENT,
        rejecting,
      ),
      QuantDesktopError,
    );
  }
});

test("run posts the declared assumptions and parses the result contract", async () => {
  const record = {
    as_of_cutoff: "2026-01-20",
    assumptions: ASSUMPTIONS,
    benchmark: {
      backtest_sha256: HASH,
      commission: "1.00",
      constrained_decisions: 0,
      cost_total: "2.00",
      final_equity: "105000.00",
      max_drawdown: "0.030000",
      return_observations: 79,
      sharpe_ratio: "0.900000",
      slippage: "1.00",
      strategy_config_sha256: HASH,
      strategy_id: "buy-and-hold",
      total_return: "0.050000",
      trade_count: 1,
      transaction_cost: "0.00",
      unfilled_shares: 0,
      volatility: "0.005000",
      zero_fill_decisions: 0,
    },
    content_sha256: HASH,
    contract_version: "quant_local_result.v1",
    corporate_actions_sha256: HASH,
    currency: "USD",
    dataset_sha256: HASH,
    excess_return: "-0.040000",
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
    strategy: {
      backtest_sha256: HASH,
      commission: "12.00",
      constrained_decisions: 0,
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
      unfilled_shares: 0,
      volatility: "0.004000",
      zero_fill_decisions: 0,
    },
    validation: {
      alpha_effective: "0.025000",
      alpha_label: "0.05",
      baseline_scenario_label: "declared",
      degrees_of_freedom: 4,
      degrees_of_freedom_bucket: null,
      first_failing_scenario_label: null,
      gaps: [],
      highest_passing_scenario_label: null,
      outcome: "rejected",
      reason_codes: [],
      report_sha256: HASH,
      scenarios: [],
      test_windows_overlap: false,
      window_count: 5,
      windows_beating_benchmark: 2,
    },
  };
  const { calls, fetcher } = recordingFetch(record);

  const result = await runQuantAnalysis(
    { assumptions: ASSUMPTIONS, operatorId: OPERATOR_ID, securityId: SECURITY_ID },
    READY_ENVIRONMENT,
    fetcher,
  );

  assert.equal(result.validation.outcome, "rejected");
  assert.equal(calls[0].url, "http://127.0.0.1:60355/v1/quant/runs");
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
    assumptions: ASSUMPTIONS,
    operator_id: OPERATOR_ID,
    security_id: SECURITY_ID,
  });
});

test("a result failing the shared contract is refused rather than displayed", async () => {
  const { fetcher } = recordingFetch({
    contract_version: "quant_local_result.v1",
    holdings: [],
    security_id: SECURITY_ID,
  });

  await assert.rejects(
    runQuantAnalysis(
      { assumptions: ASSUMPTIONS, operatorId: OPERATOR_ID, securityId: SECURITY_ID },
      READY_ENVIRONMENT,
      fetcher,
    ),
    (error: unknown) => {
      assert.ok(error instanceof QuantDesktopError);
      assert.equal(error.code, "quant_response_invalid");
      return true;
    },
  );
});

test("a run is refused when the desktop worker is not ready", async () => {
  await assert.rejects(
    runQuantAnalysis(
      { assumptions: ASSUMPTIONS, operatorId: OPERATOR_ID, securityId: SECURITY_ID },
      {},
      async () => {
        throw new Error("no request may be made without a ready worker");
      },
    ),
    (error: unknown) => {
      assert.ok(error instanceof QuantDesktopError);
      assert.equal(error.code, "quant_workspace_unavailable");
      return true;
    },
  );
});

test("the latest result is null when no run has completed", async () => {
  const { calls, fetcher } = recordingFetch({ result: null });

  const latest = await loadLatestQuantResult(
    { operatorId: OPERATOR_ID, securityId: SECURITY_ID },
    READY_ENVIRONMENT,
    fetcher,
  );

  assert.equal(latest, null);
  assert.match(calls[0].url, /\/v1\/quant\/runs\/latest\?/);
});

test("a stored latest result that fails the contract is discarded", async () => {
  const { fetcher } = recordingFetch({ result: { contract_version: "other" } });

  assert.equal(
    await loadLatestQuantResult(
      { operatorId: OPERATOR_ID, securityId: SECURITY_ID },
      READY_ENVIRONMENT,
      fetcher,
    ),
    null,
  );
});

test("the latest result is never requested without a ready worker", async () => {
  assert.equal(
    await loadLatestQuantResult(
      { operatorId: OPERATOR_ID, securityId: SECURITY_ID },
      {},
      async () => {
        throw new Error("no request may be made without a ready worker");
      },
    ),
    null,
  );
});
