/**
 * Contracts for the desktop-local Quant workspace.
 *
 * Quant is a separate bounded context. It shares the canonical `security_id`
 * with Research and Portfolio and nothing else, so these parsers do two jobs:
 * they check the shape the worker promised, and they refuse any record that
 * carries a field belonging to another domain. A Quant result that arrived
 * holding evidence, a thesis, a holding, or a broker field is not a Quant
 * result that needs repairing; it is a boundary violation, and it is rejected.
 *
 * Quant output is historical analysis of an operator-supplied dataset. It is
 * never a prediction, never a recommendation, and never Research evidence.
 */

export const QUANT_DATASET_RECEIPT_CONTRACT =
  "quant_local_dataset_receipt.v1" as const;
export const QUANT_RESULT_CONTRACT = "quant_local_result.v1" as const;

/**
 * Tokens that must never appear in a key anywhere inside a Quant payload. Each
 * one belongs to Research, Portfolio, or a broker, and none has a reason to
 * cross into a historical-analysis record.
 *
 * Matched as substrings rather than whole keys on purpose: `position_size` and
 * `holdings_value` are the same violation as `position` and `holdings`, and an
 * exact-match list would wave both through.
 */
const FORBIDDEN_KEY_TOKENS = [
  "account",
  "allocation",
  "broker",
  "committee",
  "evidence",
  "holding",
  "opinion",
  "order",
  "portfolio",
  "position",
  "recommendation",
  "signal",
  "sizing",
  "target_price",
  "thesis",
] as const;

/**
 * Every failure code the Quant workspace may report. It lives beside the
 * contracts because both the worker client and the presentation layer must
 * agree on it: the client refuses to pass on anything outside this set, and the
 * presentation layer owns a sentence for each one.
 */
export const QUANT_ERROR_CODES = [
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
  "fetch_provider_blocked",
  "fetch_provider_rejected",
  "fetch_provider_unavailable",
  "fetch_ticker_invalid",
  "fetch_window_invalid",
  "quant_request_invalid",
  "quant_response_invalid",
  "quant_workspace_unavailable",
  "run_assumptions_invalid",
  "run_dataset_invalid",
  "run_dataset_missing",
  "workspace_identity_invalid",
  "workspace_store_unsafe",
] as const;

export type QuantErrorCode = (typeof QUANT_ERROR_CODES)[number];

/** The code used whenever a reported one is not in the reviewed vocabulary. */
export const GENERIC_QUANT_ERROR_CODE: QuantErrorCode = "quant_request_invalid";

export function isQuantErrorCode(value: unknown): value is QuantErrorCode {
  return (
    typeof value === "string" &&
    (QUANT_ERROR_CODES as readonly string[]).includes(value)
  );
}

export type QuantDatasetReceipt = {
  as_of_cutoff: string;
  corporate_actions_sha256: string;
  currency: string;
  dataset_sha256: string;
  first_session: string;
  interval: "1d";
  last_session: string;
  price_basis: "unadjusted";
  series_sha256: string;
  session_count: number;
  source_content_sha256: string;
  source_id: string;
  source_revision: string;
  split_count: number;
};

export type QuantDatasetStatus = {
  contract_version: typeof QUANT_DATASET_RECEIPT_CONTRACT;
  dataset: QuantDatasetReceipt | null;
  security_id: string;
};

export type QuantOutcome = {
  backtest_sha256: string;
  commission: string;
  constrained_decisions: number;
  cost_total: string;
  final_equity: string;
  max_drawdown: string;
  return_observations: number;
  sharpe_ratio: string | null;
  slippage: string;
  strategy_config_sha256: string;
  strategy_id: string;
  total_return: string;
  trade_count: number;
  transaction_cost: string;
  unfilled_shares: number;
  volatility: string | null;
  zero_fill_decisions: number;
};

export type QuantScenarioSummary = {
  aggregate_excess: string;
  critical_value: string | null;
  label: string;
  mean_excess: string;
  passed: boolean;
  t_statistic: string | null;
  windows_beating_benchmark: number;
};

export type QuantValidation = {
  alpha_effective: string;
  alpha_label: string | null;
  baseline_scenario_label: string;
  degrees_of_freedom: number;
  degrees_of_freedom_bucket: number | null;
  first_failing_scenario_label: string | null;
  gaps: string[];
  highest_passing_scenario_label: string | null;
  outcome: "validated" | "rejected" | "insufficient_data" | "inconclusive";
  reason_codes: string[];
  report_sha256: string;
  scenarios: QuantScenarioSummary[];
  test_windows_overlap: boolean;
  window_count: number;
  windows_beating_benchmark: number;
};

export type QuantLocalResult = {
  as_of_cutoff: string;
  assumptions: Record<string, string | number>;
  benchmark: QuantOutcome;
  content_sha256: string;
  contract_version: typeof QUANT_RESULT_CONTRACT;
  corporate_actions_sha256: string;
  currency: string;
  dataset_sha256: string;
  excess_return: string;
  first_session: string;
  last_session: string;
  limitations: string[];
  security_id: string;
  series_sha256: string;
  session_count: number;
  source_content_sha256: string;
  source_id: string;
  source_revision: string;
  split_count: number;
  strategy: QuantOutcome;
  validation: QuantValidation;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function isIsoDate(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function isDecimalText(value: unknown): value is string {
  return typeof value === "string" && /^-?\d+(\.\d+)?$/.test(value);
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === "string");
}

/**
 * Depth-first scan for a field belonging to another bounded context.
 *
 * Checked on the whole payload rather than the top level: a cross-domain field
 * nested inside `assumptions` or a scenario would be just as much of a
 * violation, and just as invisible to a shallow check.
 */
function carriesForeignDomainField(value: unknown, depth = 0): boolean {
  if (depth > 8) return true;
  if (Array.isArray(value)) {
    return value.some((entry) => carriesForeignDomainField(entry, depth + 1));
  }
  if (!isRecord(value)) return false;
  for (const key of Object.keys(value)) {
    const normalized = key.toLowerCase();
    if (FORBIDDEN_KEY_TOKENS.some((token) => normalized.includes(token))) {
      return true;
    }
    if (carriesForeignDomainField(value[key], depth + 1)) return true;
  }
  return false;
}

function parseDatasetReceipt(value: unknown): QuantDatasetReceipt | null {
  if (!isRecord(value)) return null;
  if (
    !isIsoDate(value.as_of_cutoff) ||
    !isIsoDate(value.first_session) ||
    !isIsoDate(value.last_session) ||
    !isSha256(value.corporate_actions_sha256) ||
    !isSha256(value.dataset_sha256) ||
    !isSha256(value.series_sha256) ||
    !isSha256(value.source_content_sha256) ||
    typeof value.currency !== "string" ||
    !/^[A-Z]{3}$/.test(value.currency) ||
    value.interval !== "1d" ||
    value.price_basis !== "unadjusted" ||
    typeof value.source_id !== "string" ||
    value.source_id.length === 0 ||
    typeof value.source_revision !== "string" ||
    value.source_revision.length === 0 ||
    !isCount(value.session_count) ||
    !isCount(value.split_count)
  ) {
    return null;
  }
  return value as QuantDatasetReceipt;
}

export function parseQuantDatasetStatus(
  value: unknown,
): QuantDatasetStatus | null {
  if (!isRecord(value)) return null;
  if (
    value.contract_version !== QUANT_DATASET_RECEIPT_CONTRACT ||
    typeof value.security_id !== "string" ||
    carriesForeignDomainField(value)
  ) {
    return null;
  }
  if (value.dataset === null) {
    return {
      contract_version: QUANT_DATASET_RECEIPT_CONTRACT,
      dataset: null,
      security_id: value.security_id,
    };
  }
  const dataset = parseDatasetReceipt(value.dataset);
  if (dataset === null) return null;
  return {
    contract_version: QUANT_DATASET_RECEIPT_CONTRACT,
    dataset,
    security_id: value.security_id,
  };
}

function parseOutcome(value: unknown): QuantOutcome | null {
  if (!isRecord(value)) return null;
  if (
    !isSha256(value.backtest_sha256) ||
    !isSha256(value.strategy_config_sha256) ||
    typeof value.strategy_id !== "string" ||
    value.strategy_id.length === 0 ||
    !isDecimalText(value.commission) ||
    !isDecimalText(value.cost_total) ||
    !isDecimalText(value.final_equity) ||
    !isDecimalText(value.max_drawdown) ||
    !isDecimalText(value.slippage) ||
    !isDecimalText(value.total_return) ||
    !isDecimalText(value.transaction_cost) ||
    !isCount(value.constrained_decisions) ||
    !isCount(value.return_observations) ||
    !isCount(value.trade_count) ||
    !isCount(value.unfilled_shares) ||
    !isCount(value.zero_fill_decisions) ||
    !(value.sharpe_ratio === null || isDecimalText(value.sharpe_ratio)) ||
    !(value.volatility === null || isDecimalText(value.volatility))
  ) {
    return null;
  }
  return value as QuantOutcome;
}

function parseValidation(value: unknown): QuantValidation | null {
  if (!isRecord(value)) return null;
  const outcomes = ["validated", "rejected", "insufficient_data", "inconclusive"];
  if (
    typeof value.outcome !== "string" ||
    !outcomes.includes(value.outcome) ||
    !isSha256(value.report_sha256) ||
    !isDecimalText(value.alpha_effective) ||
    !isStringArray(value.gaps) ||
    !isStringArray(value.reason_codes) ||
    !isCount(value.degrees_of_freedom) ||
    !isCount(value.window_count) ||
    !isCount(value.windows_beating_benchmark) ||
    typeof value.baseline_scenario_label !== "string" ||
    typeof value.test_windows_overlap !== "boolean" ||
    !Array.isArray(value.scenarios)
  ) {
    return null;
  }
  for (const scenario of value.scenarios) {
    if (
      !isRecord(scenario) ||
      typeof scenario.label !== "string" ||
      typeof scenario.passed !== "boolean" ||
      !isDecimalText(scenario.aggregate_excess) ||
      !isDecimalText(scenario.mean_excess) ||
      !isCount(scenario.windows_beating_benchmark)
    ) {
      return null;
    }
  }
  return value as QuantValidation;
}

export function parseQuantLocalResult(value: unknown): QuantLocalResult | null {
  if (!isRecord(value)) return null;
  if (
    value.contract_version !== QUANT_RESULT_CONTRACT ||
    typeof value.security_id !== "string" ||
    !isSha256(value.content_sha256) ||
    !isSha256(value.dataset_sha256) ||
    !isSha256(value.series_sha256) ||
    !isSha256(value.corporate_actions_sha256) ||
    !isSha256(value.source_content_sha256) ||
    !isIsoDate(value.as_of_cutoff) ||
    !isIsoDate(value.first_session) ||
    !isIsoDate(value.last_session) ||
    !isDecimalText(value.excess_return) ||
    !isCount(value.session_count) ||
    !isCount(value.split_count) ||
    !isStringArray(value.limitations) ||
    !isRecord(value.assumptions) ||
    typeof value.source_id !== "string" ||
    typeof value.source_revision !== "string" ||
    typeof value.currency !== "string" ||
    carriesForeignDomainField(value)
  ) {
    return null;
  }
  const strategy = parseOutcome(value.strategy);
  const benchmark = parseOutcome(value.benchmark);
  const validation = parseValidation(value.validation);
  if (strategy === null || benchmark === null || validation === null) {
    return null;
  }
  return value as QuantLocalResult;
}
