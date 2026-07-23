import type { HoldingSnapshotContext } from "@iros/types";

type HoldingRow = {
  snapshot_id: string;
  portfolio_key: string;
  account_label: string;
  currency: string | null;
  currency_state: "declared" | "indeterminate";
  observed_at: string | null;
  timing_state: "declared" | "indeterminate";
  observation_time_text: string;
  source_type: "user_supplied_screenshot";
  source_sha256: string;
  captured_at: string;
  content_sha256: string;
  expected_position_count: number;
  total_market_value: number | string;
  total_cost_basis: number | string;
  total_unrealized_pnl: number | string;
  position_id: string;
  security_id: string;
  ordinal: number;
  symbol_observed: string;
  quantity: number | string;
  average_cost: number | string;
  observed_price: number | string;
  observed_market_value: number | string;
  cost_basis: number | string;
  unrealized_pnl: number | string;
};

export type HoldingsLoadResult = {
  snapshot: HoldingSnapshotContext | null;
  unavailableReason: string | null;
};

export function mapHoldingRows(
  rows: HoldingRow[],
): HoldingSnapshotContext | null {
  if (!rows.length) return null;
  const ordered = [...rows].sort((left, right) => left.ordinal - right.ordinal);
  const first = ordered[0];
  if (
    ordered.length !== first.expected_position_count ||
    ordered.some(
      (row) =>
        row.snapshot_id !== first.snapshot_id ||
        row.content_sha256 !== first.content_sha256 ||
        row.portfolio_key !== first.portfolio_key,
    ) ||
    new Set(ordered.map((row) => row.ordinal)).size !== ordered.length ||
    new Set(ordered.map((row) => row.security_id)).size !== ordered.length
  ) {
    throw new Error("Holdings API returned inconsistent immutable snapshot");
  }
  return {
    snapshotId: first.snapshot_id,
    portfolioKey: first.portfolio_key,
    accountLabel: first.account_label,
    currency: first.currency,
    currencyState: first.currency_state,
    observedAt: first.observed_at,
    timingState: first.timing_state,
    observationTimeText: first.observation_time_text,
    sourceType: first.source_type,
    sourceSha256: first.source_sha256,
    capturedAt: first.captured_at,
    contentSha256: first.content_sha256,
    positionCount: first.expected_position_count,
    totalMarketValue: Number(first.total_market_value),
    totalCostBasis: Number(first.total_cost_basis),
    totalUnrealizedPnl: Number(first.total_unrealized_pnl),
    positions: ordered.map((row) => ({
      positionId: row.position_id,
      securityId: row.security_id,
      ordinal: row.ordinal,
      ticker: row.symbol_observed,
      quantity: Number(row.quantity),
      averageCost: Number(row.average_cost),
      observedPrice: Number(row.observed_price),
      observedMarketValue: Number(row.observed_market_value),
      costBasis: Number(row.cost_basis),
      unrealizedPnl: Number(row.unrealized_pnl),
    })),
  };
}

export async function loadLatestHoldings(
  portfolioKey = "primary-brokerage",
): Promise<HoldingsLoadResult> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_latest_holdings")
    .select(
      "snapshot_id,portfolio_key,account_label,currency,currency_state,observed_at,timing_state,observation_time_text,source_type,source_sha256,captured_at,content_sha256,expected_position_count,total_market_value,total_cost_basis,total_unrealized_pnl,position_id,security_id,ordinal,symbol_observed,quantity,average_cost,observed_price,observed_market_value,cost_basis,unrealized_pnl",
    )
    .eq("portfolio_key", portfolioKey)
    .order("ordinal", { ascending: true });
  if (error) {
    if (error.code === "42P01" || error.code === "PGRST205") {
      return {
        snapshot: null,
        unavailableReason: "Private holdings storage is not migrated.",
      };
    }
    throw new Error(`Holdings API failed: ${error.message}`);
  }
  return {
    snapshot: mapHoldingRows((data ?? []) as HoldingRow[]),
    unavailableReason: null,
  };
}
