// Imported by path rather than through the `@iros/types` alias because the
// vocabulary is a runtime value, and a relative path keeps this module
// directly runnable under `node --test`.
import {
  GENERIC_QUANT_ERROR_CODE,
  isQuantErrorCode,
} from "../../../packages/types/quant-workspace.ts";
import type { QuantDatasetReceipt, QuantLocalResult } from "@iros/types";

/**
 * Presentation model for the Quant workspace.
 *
 * The worker emits identity hashes, aggregate numbers, and codes. This module
 * turns those into something a person can read, and it is the only place the
 * wording lives. Two rules shape all of it.
 *
 * **No raw code ever reaches a person.** Every error, gap, and limitation code
 * has a sentence here, including an unrecognised one: a future worker version
 * emitting a code this build has never seen must still produce readable text
 * rather than leaking an identifier into the page.
 *
 * **Nothing here advises.** Every metric explanation describes what the number
 * measured over a fixed history. None of them says what to do about it, what
 * is likely next, or what anyone should hold. A Quant result is historical
 * analysis of an operator-supplied dataset and is never investment advice,
 * never a prediction, and never Research evidence.
 */

export type QuantMetric = {
  label: string;
  plainLanguage: string;
  value: string;
};

export type QuantDetailEntry = {
  label: string;
  value: string;
};

export type QuantGap = {
  explanation: string;
  label: string;
};

export type QuantBenchmarkComparison = {
  benchmarkReturn: string;
  excessReturn: string;
  label: string;
  plainLanguage: string;
  strategyAhead: boolean;
  strategyReturn: string;
};

export type QuantValidationView = {
  gaps: QuantGap[];
  headline: string;
  plainLanguage: string;
  validated: boolean;
  windowCount: number;
  windowsBeatingBenchmark: number;
};

export type QuantWorkspaceView = {
  benchmark: QuantBenchmarkComparison | null;
  canRun: boolean;
  datasetSummary: {
    cutoff: string;
    currency: string;
    firstSession: string;
    lastSession: string;
    sessionCount: number;
    sourceId: string;
    sourceRevision: string;
    splitCount: number;
  } | null;
  detail: QuantDetailEntry[];
  disclaimer: string;
  errorMessage: string | null;
  headline: string;
  limitations: string[];
  metrics: QuantMetric[];
  state: "unavailable" | "no_dataset" | "dataset_ready" | "result_ready";
  validation: QuantValidationView | null;
};

export const QUANT_DISCLAIMER =
  "This is historical analysis of a dataset you supplied. It measures what a " +
  "fixed rule would have done over sessions that already happened. It is not " +
  "a forecast, not advice, and not evidence for any research thesis.";

const ERROR_MESSAGES: Record<string, string> = {
  dataset_contract_invalid:
    "That file is not in the supported dataset format. It must be JSON containing the daily OHLCV contract, with no extra fields.",
  dataset_currency_invalid:
    "The currency must be a three-letter upper-case code such as USD.",
  dataset_cutoff_invalid:
    "The as-of cutoff must be a calendar date written as YYYY-MM-DD.",
  dataset_file_unreadable:
    "That file could not be read. Check the path points at a file this app can open.",
  dataset_future_data:
    "The file contains a session or a corporate action dated after its own as-of cutoff, so some of it was not knowable at that point in time.",
  dataset_hash_mismatch:
    "The declared content hash does not match the rows in the file, so the file changed after that hash was recorded.",
  dataset_path_invalid:
    "The dataset path must be an absolute path, and neither the file nor its folder may be a shortcut to somewhere else.",
  dataset_rows_invalid:
    "At least one row does not satisfy the bar contract. Prices must be written as text rather than decimals, the high must be the highest value, and at least two sessions are needed.",
  dataset_security_mismatch:
    "That file declares a different security from the one selected here.",
  dataset_sessions_invalid:
    "Sessions must run in date order with no repeats. A duplicate or out-of-order date was found.",
  dataset_split_uncovered:
    "A corporate action falls on a date the file does not trade into, so it could never be applied.",
  dataset_too_large: "That file is larger than this workspace accepts.",
  quant_request_invalid: "That request was not in a form this workspace accepts.",
  quant_workspace_unavailable:
    "The local analysis service is not running, so datasets and analyses are unavailable.",
  run_assumptions_invalid:
    "One of the assumptions is outside its allowed range. Every value must be stated, and none may be negative.",
  run_dataset_invalid:
    "The stored dataset no longer satisfies its own contract, so nothing was computed. Import it again.",
  run_dataset_missing: "Import a dataset for this security before running an analysis.",
  workspace_identity_invalid: "That request did not name a valid security.",
  workspace_store_unsafe:
    "The local storage location could not be used safely, so nothing was written.",
};

const GAP_MESSAGES: Record<string, string> = {
  alpha_outside_critical_value_table:
    "The significance level asked for sits outside the table of critical values used here, so no pass or fail could be decided.",
  below_smallest_significance_sample:
    "There were fewer windows than the smallest sample the significance table covers, so no threshold applied.",
  benchmark_unreachable:
    "In at least one window the market could not absorb even the buy-and-hold order at the capacity limit set, so that comparison is not a fair one.",
  dispersion_unmeasurable:
    "The results did not vary enough to measure spread, so no statistic could be computed from them.",
  fails_under_higher_costs:
    "The result did not survive the higher-cost scenario, so it depends on costs staying near the level declared.",
  insufficient_windows:
    "There was not enough history to build the number of test windows required, so no verdict was reached.",
  overlapping_test_windows:
    "The test windows overlap, so they share sessions and are not independent observations of the same rule.",
};

const LIMITATION_MESSAGES: Record<string, string> = {
  declared_trials_unverifiable:
    "The number of configurations tried is what you declared. Nothing here can check how many were actually attempted before this one.",
  historical_analysis_not_prediction:
    "This measures a fixed rule against sessions that already happened. It says nothing about what comes next.",
  no_dividends_modelled:
    "Cash dividends are not modelled at all, so total returns for a dividend-paying security are understated.",
  operator_declared_provenance:
    "The source, revision, and cutoff are what the file declared. Nothing here can confirm the data was really available on that date.",
  single_security_no_universe:
    "This covers one security you chose. It says nothing about the securities that existed at the time, so it cannot rule out survivorship bias.",
  split_adjusted_closes_only:
    "Signals read closes adjusted for the declared stock splits only. Any other corporate action is absent.",
};

function humanize(code: string): string {
  const spaced = code.replace(/_/g, " ").trim();
  return spaced.length === 0 ? "" : `${spaced[0].toUpperCase()}${spaced.slice(1)}.`;
}

/**
 * The error code carried by a URL, reduced to something safe to render.
 *
 * The query string is supplied by whoever opened the link, not by the worker.
 * Without this, a crafted URL could put arbitrary text into the workspace under
 * the app's own styling. An absent value is no error; anything present but
 * outside the reviewed vocabulary becomes the generic refusal.
 */
export function quantErrorCodeFromQuery(value: unknown): string | null {
  if (value === undefined || value === null || value === "") return null;
  return isQuantErrorCode(value) ? value : GENERIC_QUANT_ERROR_CODE;
}

/** Plain language for one worker error code, known or not. */
export function quantErrorMessage(code: string): string {
  return (
    ERROR_MESSAGES[code] ??
    `The local analysis service reported a problem this version does not recognise: ${humanize(
      code,
    )} Nothing was changed.`
  );
}

/** Plain language for one validation gap code, known or not. */
export function quantGapMessage(code: string): string {
  return (
    GAP_MESSAGES[code] ??
    `This analysis reported a limit this version does not recognise: ${humanize(code)}`
  );
}

/** Plain language for one standing limitation code, known or not. */
export function quantLimitationMessage(code: string): string {
  return (
    LIMITATION_MESSAGES[code] ??
    `This analysis carries a limitation this version does not recognise: ${humanize(
      code,
    )}`
  );
}

function gapLabel(code: string): string {
  const spaced = code.replace(/_/g, " ");
  return spaced.length === 0 ? "" : `${spaced[0].toUpperCase()}${spaced.slice(1)}`;
}

/**
 * Percent text from decimal-ratio text.
 *
 * The worker sends exact decimal text and this multiplies it by a hundred for
 * reading. Two places are enough to read and few enough to avoid implying the
 * measurement is finer than the dataset supports.
 */
export function quantPercent(value: string): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return value;
  return `${(parsed * 100).toFixed(2)}%`;
}

function unmeasured(value: string | null): string {
  return value === null ? "Not measurable" : value;
}

function validationHeadline(result: QuantLocalResult): string {
  switch (result.validation.outcome) {
    case "insufficient_data":
      return "Not enough history to test this rule";
    case "validated":
      return "The excess over buy and hold survived out-of-sample testing";
    case "rejected":
      return "The excess over buy and hold did not survive out-of-sample testing";
    default:
      return "Out-of-sample testing reached no conclusion";
  }
}

function validationPlainLanguage(result: QuantLocalResult): string {
  const { validation } = result;
  if (validation.outcome === "insufficient_data") {
    return (
      "The history was split into fewer usable windows than the schedule " +
      "requires, so no statistical claim was attempted. A longer dataset or a " +
      "shorter training window would produce more windows."
    );
  }
  return (
    `The history was split into ${validation.window_count} windows. The rule ` +
    `was ahead of buy and hold in ${validation.windows_beating_benchmark} of ` +
    "them under the costs you declared. A window count this small is a weak " +
    "sample, whichever way it came out."
  );
}

function metricsFor(result: QuantLocalResult): QuantMetric[] {
  const { strategy } = result;
  return [
    {
      label: "Total return",
      plainLanguage:
        "How much the starting cash grew or shrank across the whole dataset, after every cost you declared.",
      value: quantPercent(strategy.total_return),
    },
    {
      label: "Maximum drawdown",
      plainLanguage:
        "The deepest fall from a previous high point along the way. It is the worst stretch someone following this rule would have sat through.",
      value: quantPercent(strategy.max_drawdown),
    },
    {
      label: "Volatility",
      plainLanguage:
        "How much the daily result moved around its own average. A larger number means a bumpier ride for the same end point.",
      value: unmeasured(strategy.volatility),
    },
    {
      label: "Return per unit of movement",
      plainLanguage:
        "The average daily result divided by how much it moved around, scaled to a year. It compares two rules on the same footing, and it is not a rate of return.",
      value: unmeasured(strategy.sharpe_ratio),
    },
    {
      label: "Trades",
      plainLanguage:
        "How many times the rule actually bought or sold. More trades means more cost and more chances for the market not to fill the order.",
      value: String(strategy.trade_count),
    },
    {
      label: "Unfilled shares",
      plainLanguage:
        "Shares the rule asked for and did not get, because the session traded too little volume for the participation limit you set. Unfilled orders are cancelled, not carried over.",
      value: String(strategy.unfilled_shares),
    },
    {
      label: "Cost impact",
      plainLanguage:
        "Commission, transaction charges, and slippage added together, in cash. This is what the rule paid to trade, and it is already taken out of the return above.",
      value: `${strategy.cost_total} ${result.currency}`,
    },
    {
      label: "Final value",
      plainLanguage:
        "What the starting cash was worth at the last session in the dataset, counting cash and shares together.",
      value: `${strategy.final_equity} ${result.currency}`,
    },
  ];
}

function detailFor(
  dataset: QuantDatasetReceipt,
  result: QuantLocalResult | null,
): QuantDetailEntry[] {
  const entries: QuantDetailEntry[] = [
    { label: "Source", value: dataset.source_id },
    { label: "Source revision", value: dataset.source_revision },
    { label: "As-of cutoff", value: dataset.as_of_cutoff },
    {
      label: "Sessions covered",
      value: `${dataset.first_session} to ${dataset.last_session} (${dataset.session_count})`,
    },
    { label: "Bar interval", value: dataset.interval },
    { label: "Price basis", value: dataset.price_basis },
    { label: "Corporate actions", value: String(dataset.split_count) },
    { label: "Dataset hash", value: dataset.dataset_sha256 },
    { label: "Source payload hash", value: dataset.source_content_sha256 },
  ];
  if (result === null) return entries;
  entries.push(
    { label: "Strategy", value: result.strategy.strategy_id },
    {
      label: "Strategy configuration hash",
      value: result.strategy.strategy_config_sha256,
    },
    { label: "Benchmark", value: result.benchmark.strategy_id },
    { label: "Result hash", value: result.content_sha256 },
    { label: "Validation report hash", value: result.validation.report_sha256 },
  );
  for (const [key, value] of Object.entries(result.assumptions)) {
    entries.push({ label: `Assumption: ${key.replace(/_/g, " ")}`, value: String(value) });
  }
  return entries;
}

/**
 * Build the whole workspace view from what is currently known.
 *
 * Deliberately total: every combination of missing worker, missing dataset,
 * error code, and completed result maps to exactly one state, so the page
 * never has to guess what to render.
 */
export function buildQuantWorkspaceView({
  dataset,
  errorCode,
  result,
  workspaceAvailable,
}: {
  dataset: QuantDatasetReceipt | null;
  errorCode: string | null;
  result: QuantLocalResult | null;
  workspaceAvailable: boolean;
}): QuantWorkspaceView {
  const errorMessage = errorCode === null ? null : quantErrorMessage(errorCode);
  const base = {
    benchmark: null,
    canRun: false,
    datasetSummary: null,
    detail: [] as QuantDetailEntry[],
    disclaimer: QUANT_DISCLAIMER,
    errorMessage,
    limitations: [] as string[],
    metrics: [] as QuantMetric[],
    validation: null,
  };

  if (!workspaceAvailable) {
    return {
      ...base,
      headline:
        "The desktop app is not running this analysis service, so no dataset can be imported or analysed.",
      state: "unavailable",
    };
  }
  if (dataset === null) {
    return {
      ...base,
      headline:
        "Import a daily price dataset for this security to begin. Nothing is fetched for you and no account data is used.",
      state: "no_dataset",
    };
  }

  const datasetSummary = {
    cutoff: dataset.as_of_cutoff,
    currency: dataset.currency,
    firstSession: dataset.first_session,
    lastSession: dataset.last_session,
    sessionCount: dataset.session_count,
    sourceId: dataset.source_id,
    sourceRevision: dataset.source_revision,
    splitCount: dataset.split_count,
  };

  if (result === null) {
    return {
      ...base,
      canRun: true,
      datasetSummary,
      detail: detailFor(dataset, null),
      headline: `A dataset of ${dataset.session_count} daily sessions is ready, current as of ${dataset.as_of_cutoff}.`,
      state: "dataset_ready",
    };
  }

  const strategyAhead = Number(result.excess_return) > 0;
  return {
    benchmark: {
      benchmarkReturn: quantPercent(result.benchmark.total_return),
      excessReturn: result.excess_return,
      label: "Buy and hold",
      plainLanguage: strategyAhead
        ? "The rule ended ahead of buying once at the start and keeping it, after the same costs and the same capacity limit."
        : "The rule ended behind buying once at the start and keeping it, after the same costs and the same capacity limit.",
      strategyAhead,
      strategyReturn: quantPercent(result.strategy.total_return),
    },
    canRun: true,
    datasetSummary,
    detail: detailFor(dataset, result),
    disclaimer: QUANT_DISCLAIMER,
    errorMessage,
    headline: `Analysis of ${result.session_count} daily sessions to ${result.as_of_cutoff}, using the dataset and assumptions recorded below.`,
    limitations: result.limitations.map(quantLimitationMessage),
    metrics: metricsFor(result),
    state: "result_ready",
    validation: {
      gaps: result.validation.gaps.map((code) => ({
        explanation: quantGapMessage(code),
        label: gapLabel(code),
      })),
      headline: validationHeadline(result),
      plainLanguage: validationPlainLanguage(result),
      validated: result.validation.outcome === "validated",
      windowCount: result.validation.window_count,
      windowsBeatingBenchmark: result.validation.windows_beating_benchmark,
    },
  };
}
