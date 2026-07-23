import type { HoldingSnapshotContext } from "@iros/types";

export type HoldingPositionSummary =
  HoldingSnapshotContext["positions"][number] & {
    unrealizedPnlPercent: number;
  };

export type HoldingsSummary = {
  currencyLabel: string;
  timingLabel: string;
  totalUnrealizedPnlPercent: number;
  positions: HoldingPositionSummary[];
};

export function summarizeHoldings(
  snapshot: HoldingSnapshotContext,
): HoldingsSummary {
  return {
    currencyLabel:
      snapshot.currencyState === "declared" && snapshot.currency
        ? snapshot.currency
        : "Currency unspecified",
    timingLabel:
      snapshot.timingState === "declared" && snapshot.observedAt
        ? snapshot.observedAt
        : snapshot.observationTimeText,
    totalUnrealizedPnlPercent:
      snapshot.totalCostBasis > 0
        ? (snapshot.totalUnrealizedPnl / snapshot.totalCostBasis) * 100
        : 0,
    positions: snapshot.positions.map((position) => ({
      ...position,
      unrealizedPnlPercent:
        position.costBasis > 0
          ? (position.unrealizedPnl / position.costBasis) * 100
          : 0,
    })),
  };
}
