import type { MoomooDesktopHoldings } from "./moomoo-desktop.ts";

const DECIMAL_PATTERN = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;

type PortfolioMirrorRow = {
  account_id: string;
  provider: "moomoo_rest" | "moomoo_opend";
  provider_transport: "web_rest_oauth" | "opend_local_tcp";
  snapshot_id: string;
  content_sha256: string;
  captured_at: string;
  checked_at: string;
  expected_position_count: number;
  unmapped_count: number;
  ambiguous_count: number;
  precision_risk_count: number;
  read_only_assurance: "read_only_scopes_no_order_surface";
  position_id: string;
  ordinal: number;
  provider_symbol: string;
  display_name: string;
  canonical_ticker: string;
  security_id: string | null;
  mapping_state: "mapped" | "unmapped" | "ambiguous";
  primary_listing_exchange: string | null;
  position_side: string;
  quantity_text: string;
  available_quantity_text: string;
  average_cost_text: string | null;
  average_cost_state: "reported" | "provider_invalid";
  last_price_text: string;
  market_value_text: string;
  currency: string;
  unrealized_pnl_text: string | null;
  unrealized_pnl_state: "reported" | "provider_invalid";
  precision_risk_fields: string[];
};

export type PortfolioMirrorLoadResult = {
  holdings: MoomooDesktopHoldings | null;
  unavailableReason: string | null;
};

export function mapPortfolioMirrorRows(
  rows: PortfolioMirrorRow[],
): MoomooDesktopHoldings | null {
  if (!rows.length) return null;
  const byAccount = new Map<string, PortfolioMirrorRow[]>();
  for (const row of rows) {
    const group = byAccount.get(row.account_id) ?? [];
    group.push(row);
    byAccount.set(row.account_id, group);
  }
  const accountIds = [...byAccount.keys()].sort();
  const accountIndexes = new Map(
    accountIds.map((accountId, index) => [accountId, index + 1]),
  );
  for (const accountRows of byAccount.values()) {
    const first = accountRows[0];
    if (
      accountRows.length !== first.expected_position_count ||
      accountRows.some(
        (row) =>
          row.snapshot_id !== first.snapshot_id ||
          row.content_sha256 !== first.content_sha256 ||
          row.expected_position_count !== first.expected_position_count,
      ) ||
      new Set(accountRows.map((row) => row.ordinal)).size !== accountRows.length
    ) {
      throw new Error("Portfolio API returned inconsistent immutable snapshot");
    }
  }
  const ordered = [...rows].sort((left, right) => {
    const accountOrder = left.account_id.localeCompare(right.account_id);
    return accountOrder || left.ordinal - right.ordinal;
  });
  if (ordered.some((row) => !isValidRow(row))) {
    throw new Error("Portfolio API returned invalid mirror data");
  }
  return {
    accountCount: accountIds.length,
    checkedAt: ordered.reduce(
      (latest, row) => row.checked_at > latest ? row.checked_at : latest,
      ordered[0].checked_at,
    ),
    positionCount: ordered.length,
    positions: ordered.map((row) => ({
      accountIndex: accountIndexes.get(row.account_id)!,
      canonicalTicker: row.canonical_ticker,
      code: row.provider_symbol,
      costPrice: row.average_cost_text,
      costPriceValid: row.average_cost_state === "reported",
      currency: row.currency,
      mappingState: row.mapping_state,
      marketValue: row.market_value_text,
      nominalPrice: row.last_price_text,
      plValue: row.unrealized_pnl_text,
      plValueValid: row.unrealized_pnl_state === "reported",
      positionSide: row.position_side,
      quantity: row.quantity_text,
      securityId: row.security_id,
      stockName: row.display_name,
    })),
    source: "hosted_snapshot",
  };
}

export async function loadLatestPortfolioMirror(): Promise<PortfolioMirrorLoadResult> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_portfolio_latest_broker_positions")
    .select(
      "account_id,provider,provider_transport,snapshot_id,content_sha256,captured_at,checked_at,expected_position_count,unmapped_count,ambiguous_count,precision_risk_count,read_only_assurance,position_id,ordinal,provider_symbol,display_name,canonical_ticker,security_id,mapping_state,primary_listing_exchange,position_side,quantity_text,available_quantity_text,average_cost_text,average_cost_state,last_price_text,market_value_text,currency,unrealized_pnl_text,unrealized_pnl_state,precision_risk_fields",
    )
    .order("account_id", { ascending: true })
    .order("ordinal", { ascending: true });
  if (error) {
    if (error.code === "42P01" || error.code === "PGRST205") {
      return {
        holdings: null,
        unavailableReason: "Portfolio mirror storage is not migrated.",
      };
    }
    throw new Error(`Portfolio mirror API failed: ${error.message}`);
  }
  return {
    holdings: mapPortfolioMirrorRows((data ?? []) as PortfolioMirrorRow[]),
    unavailableReason: null,
  };
}

function isValidRow(row: PortfolioMirrorRow) {
  const requiredDecimals = [
    row.quantity_text,
    row.available_quantity_text,
    row.last_price_text,
    row.market_value_text,
  ];
  return (
    requiredDecimals.every((value) => DECIMAL_PATTERN.test(value)) &&
    (row.average_cost_text === null || DECIMAL_PATTERN.test(row.average_cost_text)) &&
    (row.unrealized_pnl_text === null || DECIMAL_PATTERN.test(row.unrealized_pnl_text)) &&
    row.read_only_assurance === "read_only_scopes_no_order_surface" &&
    (row.mapping_state === "mapped" ? row.security_id !== null : row.security_id === null)
  );
}
