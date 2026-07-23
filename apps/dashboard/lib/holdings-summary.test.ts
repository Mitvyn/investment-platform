import assert from "node:assert/strict";
import test from "node:test";

import type { HoldingSnapshotContext } from "@iros/types";

import { summarizeHoldings } from "./holdings-summary.ts";

const SNAPSHOT: HoldingSnapshotContext = {
  snapshotId: "11111111-1111-4111-8111-111111111111",
  portfolioKey: "primary-brokerage",
  accountLabel: "Primary brokerage",
  currency: null,
  currencyState: "indeterminate",
  observedAt: null,
  timingState: "indeterminate",
  observationTimeText: "16:00; date and timezone absent",
  sourceType: "user_supplied_screenshot",
  sourceSha256: "a".repeat(64),
  capturedAt: "2026-07-22T08:00:00+00:00",
  contentSha256: "b".repeat(64),
  positionCount: 2,
  totalMarketValue: 44,
  totalCostBasis: 41.25,
  totalUnrealizedPnl: 2.75,
  positions: [
    {
      positionId: "22222222-2222-4222-8222-222222222222",
      securityId: "33333333-3333-4333-8333-333333333333",
      ordinal: 1,
      ticker: "ALFA",
      quantity: 2,
      averageCost: 10,
      observedPrice: 9.5,
      observedMarketValue: 19,
      costBasis: 20,
      unrealizedPnl: -1,
    },
    {
      positionId: "44444444-4444-4444-8444-444444444444",
      securityId: "55555555-5555-4555-8555-555555555555",
      ordinal: 2,
      ticker: "BETA",
      quantity: 10,
      averageCost: 2.125,
      observedPrice: 2.5,
      observedMarketValue: 25,
      costBasis: 21.25,
      unrealizedPnl: 3.75,
    },
  ],
};

test("summarizes operator observation without inventing currency or timing", () => {
  const summary = summarizeHoldings(SNAPSHOT);

  assert.equal(summary.currencyLabel, "Currency unspecified");
  assert.equal(summary.timingLabel, "16:00; date and timezone absent");
  assert.equal(summary.totalUnrealizedPnlPercent, 6.666666666666667);
  assert.equal(summary.positions[0].unrealizedPnlPercent, -5);
});
