export type FinancialMetric = {
  metricKey: string;
  metricLabel: string;
  metricKind: "reported" | "calculated";
  value: number;
  unit: "USD_millions" | "percent" | "quarters";
  sourcePeriod: string;
  comparisonPeriod: string | null;
  formula: string | null;
  locator: string;
  passage: string;
  passageSha256: string;
  sourceTitle: string;
  publishedAt: string;
  sourceUrl: string;
  retrievedAt: string;
};

export type CatalystContext = {
  title: string;
  status: "expected" | "occurred" | "delayed" | "cancelled";
  windowStart: string;
  windowEnd: string;
  locator: string;
  passage: string;
  passageSha256: string;
  sourceTitle: string;
  publishedAt: string;
  sourceUrl: string;
  retrievedAt: string;
};

export type MarketContext = {
  provider: "twelve_data";
  exchange: string;
  currency: string;
  marketTime: string;
  close: number;
  previousClose: number;
  change: number;
  percentChange: number;
  volume: number | null;
  isMarketOpen: boolean;
  sourceUrl: string;
  retrievedAt: string;
};

export type RiskContext = {
  title: string;
  riskType: "financial" | "clinical" | "regulatory" | "execution";
  severity: "low" | "medium" | "high";
  status: "active" | "mitigated" | "realized" | "invalidated";
  locator: string;
  passage: string;
  passageSha256: string;
  sourceTitle: string;
  publishedAt: string;
  sourceUrl: string;
  retrievedAt: string;
};

export type WatchlistItem = {
  ticker: string;
  companyName: string;
  disposition: "monitor" | "deep_research" | "decision_ready";
  addedAt: string;
  updatedAt: string;
};

export type TickerContext = {
  financialMetrics: FinancialMetric[];
  catalyst: CatalystContext | null;
  risk: RiskContext | null;
  market: MarketContext | null;
};
