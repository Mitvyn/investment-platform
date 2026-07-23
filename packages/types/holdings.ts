export type HoldingPositionContext = {
  positionId: string;
  securityId: string;
  ordinal: number;
  ticker: string;
  quantity: number;
  averageCost: number;
  observedPrice: number;
  observedMarketValue: number;
  costBasis: number;
  unrealizedPnl: number;
};

export type HoldingSnapshotContext = {
  snapshotId: string;
  portfolioKey: string;
  accountLabel: string;
  currency: string | null;
  currencyState: "declared" | "indeterminate";
  observedAt: string | null;
  timingState: "declared" | "indeterminate";
  observationTimeText: string;
  sourceType: "user_supplied_screenshot";
  sourceSha256: string;
  capturedAt: string;
  contentSha256: string;
  positionCount: number;
  totalMarketValue: number;
  totalCostBasis: number;
  totalUnrealizedPnl: number;
  positions: HoldingPositionContext[];
};
