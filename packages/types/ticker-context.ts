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
  provider: "twelve_data" | "yahoo_finance_via_yfinance";
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

export type MarketBarContext = {
  barId: string;
  sessionDate: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  dividends: number;
  stockSplits: number;
  sessionStatus: "completed";
  barSha256: string;
};

export type MarketSeriesContext = {
  securityId: string;
  seriesId: string;
  ticker: string;
  provider: "yahoo_finance_via_yfinance";
  providerConfigVersion: string;
  exchange: string;
  currency: string;
  interval: "1d";
  adjustmentStatus: "unadjusted";
  sessionStart: string;
  sessionEnd: string;
  sourceUrl: string;
  retrievedAt: string;
  responseSha256: string;
  bars: MarketBarContext[];
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
  securityId: string | null;
  ticker: string;
  companyName: string;
  disposition: "monitor" | "deep_research" | "decision_ready";
  addedAt: string;
  updatedAt: string;
};

export type SecurityDirectoryItem = {
  securityId: string;
  cik: string;
  ticker: string;
  companyName: string;
  primaryListingExchange: string;
};

export type TickerContext = {
  financialMetrics: FinancialMetric[];
  catalyst: CatalystContext | null;
  risk: RiskContext | null;
  market: MarketContext | null;
  marketSeries: MarketSeriesContext | null;
};
