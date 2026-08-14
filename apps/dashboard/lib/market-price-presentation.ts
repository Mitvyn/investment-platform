import type { MarketBarContext } from "@iros/types";

export type MarketPriceFormat = {
  type: "price";
  precision: 2 | 4;
  minMove: 0.01 | 0.0001;
};

export function marketPriceFormat(prices: number[]): MarketPriceFormat {
  const usesSubDollarPrecision = prices.some(
    (price) => Math.abs(price) > 0 && Math.abs(price) < 1,
  );
  return usesSubDollarPrecision
    ? { type: "price", precision: 4, minMove: 0.0001 }
    : { type: "price", precision: 2, minMove: 0.01 };
}

export function marketHistoryRows(
  bars: MarketBarContext[],
  limit = 10,
): MarketBarContext[] {
  return bars.slice(-limit).reverse();
}

export const MARKET_RANGE_KEYS = ["1m", "3m", "6m", "ytd", "1y", "all"] as const;

export type MarketRangeKey = (typeof MARKET_RANGE_KEYS)[number];

export const MARKET_RANGE_LABELS: Record<MarketRangeKey, string> = {
  "1m": "1M",
  "3m": "3M",
  "6m": "6M",
  ytd: "YTD",
  "1y": "1Y",
  all: "All",
};

export type MarketVisibleRange = {
  from: string;
  to: string;
  barCount: number;
};

const RANGE_MONTHS: Partial<Record<MarketRangeKey, number>> = {
  "1m": 1,
  "3m": 3,
  "6m": 6,
  "1y": 12,
};

/**
 * Resolves the visible session window for a range key.
 *
 * Sessions are stored unadjusted and daily, so every range is a slice of the
 * bars already loaded. Returns null when the security has no stored sessions.
 */
export function marketVisibleRange(
  bars: MarketBarContext[],
  range: MarketRangeKey,
): MarketVisibleRange | null {
  if (bars.length === 0) return null;
  const sessions = bars.map((bar) => bar.sessionDate).sort();
  const last = sessions[sessions.length - 1];
  const first = sessions[0];
  if (range === "all") {
    return { from: first, to: last, barCount: sessions.length };
  }

  let start: string;
  if (range === "ytd") {
    start = `${last.slice(0, 4)}-01-01`;
  } else {
    const months = RANGE_MONTHS[range] ?? 12;
    const anchor = new Date(`${last}T00:00:00Z`);
    anchor.setUTCMonth(anchor.getUTCMonth() - months);
    start = anchor.toISOString().slice(0, 10);
  }

  const from = start < first ? first : start;
  return {
    from,
    to: last,
    barCount: sessions.filter((session) => session >= from).length,
  };
}

/**
 * Ranges worth offering: `all`, plus any range that genuinely narrows the
 * stored history to at least two sessions. A range wider than the stored
 * history clamps to the first session and becomes indistinguishable from
 * `all`, so offering it would imply history the security does not have.
 */
export function availableMarketRanges(
  bars: MarketBarContext[],
): MarketRangeKey[] {
  if (bars.length === 0) return [];
  const earliest = bars.map((barItem) => barItem.sessionDate).sort()[0];
  return MARKET_RANGE_KEYS.filter((range) => {
    if (range === "all") return true;
    const resolved = marketVisibleRange(bars, range);
    return (
      resolved !== null && resolved.barCount >= 2 && resolved.from > earliest
    );
  });
}

export type MarketDataRecency = {
  state: "recent" | "refresh_due";
  elapsedHours: number;
  label: string;
};

export function marketDataRecency(
  retrievedAt: string,
  now = new Date(),
): MarketDataRecency {
  const elapsedHours = Math.max(
    0,
    Math.floor((now.getTime() - new Date(retrievedAt).getTime()) / 3_600_000),
  );
  const label =
    elapsedHours < 1
      ? "Retrieved under 1h ago"
      : elapsedHours < 48
        ? `Retrieved ${elapsedHours}h ago`
        : `Retrieved ${Math.floor(elapsedHours / 24)}d ago`;
  return {
    state: elapsedHours >= 48 ? "refresh_due" : "recent",
    elapsedHours,
    label,
  };
}
