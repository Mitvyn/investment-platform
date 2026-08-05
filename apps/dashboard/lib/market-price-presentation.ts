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
