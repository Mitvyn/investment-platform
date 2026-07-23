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
