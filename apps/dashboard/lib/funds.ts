/**
 * Funds are named portfolios. `iros_v_latest_holdings` already partitions the
 * latest complete snapshot by `(operator_id, portfolio_key)`, so every distinct
 * `portfolio_key` is a fund and no schema change is required.
 *
 * Money is summed in exact integer minor units. The single-fund holdings path
 * converts to `Number` for display; aggregating across funds that way would
 * compound IEEE-754 error into the figure the operator reconciles against their
 * broker, so the arithmetic here stays in integer minor units.
 */

export const DEFAULT_FUND_KEY = "primary-brokerage";

export type FundRow = {
  portfolio_key: string;
  account_label: string;
  currency: string | null;
  currency_state: "declared" | "indeterminate";
  captured_at: string;
  expected_position_count: number;
  total_market_value: number | string;
  total_cost_basis: number | string;
  total_unrealized_pnl: number | string;
};

export type FundSummary = {
  fundKey: string;
  label: string;
  currency: string | null;
  currencyLabel: string;
  capturedAt: string;
  positionCount: number;
  marketValue: string;
  costBasis: string;
  unrealizedPnl: string;
  unrealizedPnlPercent: number | null;
};

export type FundPortfolio = {
  funds: FundSummary[];
  total: {
    marketValue: string;
    costBasis: string;
    unrealizedPnl: string;
    unrealizedPnlPercent: number | null;
    currencyLabel: string;
    mixedCurrency: boolean;
  } | null;
};

/**
 * Money is carried as a whole number of minor units. Integers stay exact in a
 * JS number up to 2^53, which is far beyond any realistic portfolio, so the
 * fractional drift that breaks naive float addition cannot occur.
 */
function toMinorUnits(value: number | string): number {
  const text = typeof value === "number" ? value.toFixed(2) : value.trim();
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match) throw new Error("fund total is not an exact decimal");
  const [, sign, whole, fraction = ""] = match;
  const cents = `${fraction}00`.slice(0, 2);
  const magnitude = Number(whole) * 100 + Number(cents);
  if (!Number.isSafeInteger(magnitude)) {
    throw new Error("fund total exceeds exact integer range");
  }
  return sign === "-" ? -magnitude : magnitude;
}

function fromMinorUnits(value: number): string {
  const negative = value < 0;
  const magnitude = Math.abs(value);
  const whole = Math.trunc(magnitude / 100);
  const cents = String(magnitude % 100).padStart(2, "0");
  return `${negative ? "-" : ""}${whole}.${cents}`;
}

function percent(pnl: number, cost: number): number | null {
  if (cost <= 0) return null;
  return (pnl / cost) * 100;
}

function humanizeFundKey(fundKey: string): string {
  return fundKey
    .split("-")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

/**
 * Groups the latest holdings rows into one summary per fund, newest first,
 * plus a portfolio total. The total is withheld when funds disagree on
 * currency, because summing across currencies would state a figure that is
 * not true in any of them.
 */
export function summarizeFunds(rows: FundRow[]): FundPortfolio {
  const byFund = new Map<string, FundRow>();
  for (const row of rows) {
    if (!byFund.has(row.portfolio_key)) byFund.set(row.portfolio_key, row);
  }

  const funds: FundSummary[] = [...byFund.values()]
    .map((row) => {
      const marketValue = toMinorUnits(row.total_market_value);
      const costBasis = toMinorUnits(row.total_cost_basis);
      const unrealizedPnl = toMinorUnits(row.total_unrealized_pnl);
      const declared =
        row.currency_state === "declared" && row.currency ? row.currency : null;
      return {
        fundKey: row.portfolio_key,
        label: row.account_label?.trim() || humanizeFundKey(row.portfolio_key),
        currency: declared,
        currencyLabel: declared ?? "Currency unspecified",
        capturedAt: row.captured_at,
        positionCount: row.expected_position_count,
        marketValue: fromMinorUnits(marketValue),
        costBasis: fromMinorUnits(costBasis),
        unrealizedPnl: fromMinorUnits(unrealizedPnl),
        unrealizedPnlPercent: percent(unrealizedPnl, costBasis),
      };
    })
    .sort((left, right) => left.label.localeCompare(right.label));

  if (funds.length === 0) return { funds, total: null };

  const currencies = new Set(funds.map((fund) => fund.currency));
  const mixedCurrency = currencies.size > 1;
  const marketValue = funds.reduce(
    (sum, fund) => sum + toMinorUnits(fund.marketValue),
    0,
  );
  const costBasis = funds.reduce(
    (sum, fund) => sum + toMinorUnits(fund.costBasis),
    0,
  );
  const unrealizedPnl = funds.reduce(
    (sum, fund) => sum + toMinorUnits(fund.unrealizedPnl),
    0,
  );

  return {
    funds,
    total: {
      marketValue: fromMinorUnits(marketValue),
      costBasis: fromMinorUnits(costBasis),
      unrealizedPnl: fromMinorUnits(unrealizedPnl),
      unrealizedPnlPercent: percent(unrealizedPnl, costBasis),
      currencyLabel: mixedCurrency
        ? "Mixed currencies"
        : (funds[0].currencyLabel ?? "Currency unspecified"),
      mixedCurrency,
    },
  };
}

export function resolveFundKey(
  requested: string | undefined,
  funds: FundSummary[],
): string | null {
  if (funds.length === 0) return null;
  const normalized = requested?.trim().toLowerCase();
  if (normalized && funds.some((fund) => fund.fundKey === normalized)) {
    return normalized;
  }
  const fallback = funds.find((fund) => fund.fundKey === DEFAULT_FUND_KEY);
  return (fallback ?? funds[0]).fundKey;
}

export async function loadFundPortfolio(): Promise<
  FundPortfolio & { unavailableReason: string | null }
> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_latest_holdings")
    .select(
      "portfolio_key,account_label,currency,currency_state,captured_at,expected_position_count,total_market_value,total_cost_basis,total_unrealized_pnl",
    )
    .order("portfolio_key", { ascending: true });
  if (error) {
    if (error.code === "42P01" || error.code === "PGRST205") {
      return {
        funds: [],
        total: null,
        unavailableReason: "Private holdings storage is not migrated.",
      };
    }
    throw new Error(`Funds API failed: ${error.message}`);
  }
  return {
    ...summarizeFunds((data ?? []) as FundRow[]),
    unavailableReason: null,
  };
}
