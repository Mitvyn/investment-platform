"use server";

import { redirect } from "next/navigation";

import {
  QuantDesktopError,
  fetchQuantDataset,
  importQuantDataset,
  runQuantAnalysis,
} from "../lib/quant-desktop";
import { loadSecurityDirectory } from "../lib/securities";
import { createClient } from "../lib/supabase/server";

/**
 * Server actions for the Quant workspace.
 *
 * Both actions derive the operator from the authenticated session and check
 * the requested security against the authenticated directory, so a form value
 * can never widen what the caller may reach. On failure they redirect back
 * with a reviewed code, never with a message: the wording lives in the
 * presentation layer, and nothing from the operator's file is ever reflected
 * into a URL.
 *
 * Neither action touches Research state, portfolio state, or a broker. Quant
 * receives one canonical security identity and one local file path.
 */

const DECIMAL_ASSUMPTION_FIELDS = [
  "alpha",
  "commission_bps",
  "commission_minimum",
  "commission_per_share",
  "cost_stress_multiplier",
  "max_participation_bps",
  "slippage_bps",
  "starting_cash",
  "transaction_cost_bps",
] as const;

const INTEGER_ASSUMPTION_FIELDS = [
  "annualisation_periods",
  "embargo_sessions",
  "lookback_sessions",
  "min_fill_shares",
  "min_total_trades",
  "min_trades_per_window",
  "min_windows",
  "step_sessions",
  "test_sessions",
  "train_sessions",
  "trials_declared",
] as const;

async function authorizedRequest(formData: FormData) {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();
  const operatorId = data?.claims?.sub;
  if (error || !data?.claims || typeof operatorId !== "string") redirect("/login");

  const securityId = String(formData.get("securityId") ?? "").trim();
  const query = new URLSearchParams({ view: "quant" });
  if (securityId) query.set("security", securityId);

  const directory = await loadSecurityDirectory();
  const entry = directory.find((candidate) => candidate.securityId === securityId);
  if (entry === undefined) {
    query.set("quant_error", "workspace_identity_invalid");
    redirect(`/?${query.toString()}`);
  }
  return { entry, operatorId, query, securityId };
}

function failureCode(error: unknown): string {
  return error instanceof QuantDesktopError ? error.code : "quant_request_invalid";
}

export async function importQuantDatasetAction(formData: FormData) {
  const { operatorId, query, securityId } = await authorizedRequest(formData);
  try {
    await importQuantDataset({
      datasetPath: String(formData.get("datasetPath") ?? ""),
      operatorId,
      securityId,
    });
  } catch (error) {
    query.set("quant_error", failureCode(error));
    redirect(`/?${query.toString()}`);
  }
  query.set("quant", "dataset_imported");
  redirect(`/?${query.toString()}`);
}

export async function fetchQuantDatasetAction(formData: FormData) {
  const { entry, operatorId, query, securityId } = await authorizedRequest(formData);
  // `authorizedRequest` already redirected if no directory entry matched, so
  // `entry` is always present here; the assertion just states that to the
  // type checker.
  const ticker = entry!.ticker;

  const start = String(formData.get("start") ?? "").trim();
  const asOfCutoff = String(formData.get("asOfCutoff") ?? "").trim();

  try {
    await fetchQuantDataset({ asOfCutoff, operatorId, securityId, start, ticker });
  } catch (error) {
    query.set("quant_error", failureCode(error));
    redirect(`/?${query.toString()}`);
  }
  query.set("quant", "dataset_fetched");
  redirect(`/?${query.toString()}`);
}

export async function runQuantAnalysisAction(formData: FormData) {
  const { operatorId, query, securityId } = await authorizedRequest(formData);

  const assumptions: Record<string, string | number> = {};
  for (const field of DECIMAL_ASSUMPTION_FIELDS) {
    assumptions[field] = String(formData.get(field) ?? "").trim();
  }
  for (const field of INTEGER_ASSUMPTION_FIELDS) {
    const raw = String(formData.get(field) ?? "").trim();
    const parsed = Number(raw);
    if (!Number.isInteger(parsed)) {
      // Refused here rather than sent on: the worker would reject it anyway,
      // and this keeps a non-numeric form value out of the request entirely.
      query.set("quant_error", "run_assumptions_invalid");
      redirect(`/?${query.toString()}`);
    }
    assumptions[field] = parsed;
  }

  try {
    await runQuantAnalysis({ assumptions, operatorId, securityId });
  } catch (error) {
    query.set("quant_error", failureCode(error));
    redirect(`/?${query.toString()}`);
  }
  query.set("quant", "analysis_complete");
  redirect(`/?${query.toString()}`);
}
