import assert from "node:assert/strict";
import test from "node:test";

import type { MarketBarContext } from "@iros/types";

import { summarizeMarketSeries } from "./market-series.ts";

function bar(
  sessionDate: string,
  open: number,
  high: number,
  low: number,
  close: number,
  volume: number | null,
): MarketBarContext {
  return {
    barId: `bar-${sessionDate}`,
    sessionDate,
    open,
    high,
    low,
    close,
    volume,
    dividends: 0,
    stockSplits: 0,
    sessionStatus: "completed",
    barSha256: "a".repeat(64),
  };
}

test("summarizes completed OHLCV without inventing insufficient volume windows", () => {
  const summary = summarizeMarketSeries([
    bar("2026-07-14", 4.9, 5.1, 4.8, 5.0, 90),
    bar("2026-07-15", 5.0, 5.3, 4.9, 5.2, 100),
    bar("2026-07-16", 5.25, 5.5, 5.1, 5.42, 200),
  ]);

  assert.equal(summary.latest.sessionDate, "2026-07-16");
  assert.equal(summary.latest.open, 5.25);
  assert.equal(summary.previousClose, 5.2);
  assert.equal(summary.change, 0.22);
  assert.equal(summary.periodHigh, 5.5);
  assert.equal(summary.periodLow, 4.8);
  assert.equal(summary.averageVolume20, null);
  assert.equal(summary.relativeVolume20, null);
  assert.equal(summary.sessionCount, 3);
});

test("derives 20-session average and relative volume from complete observations", () => {
  const bars = Array.from({ length: 20 }, (_, index) =>
    bar(
      `2026-06-${String(index + 1).padStart(2, "0")}`,
      10,
      11,
      9,
      10,
      index === 19 ? 200 : 100,
    ),
  );

  const summary = summarizeMarketSeries(bars);

  assert.equal(summary.averageVolume20, 105);
  assert.ok(Math.abs(summary.relativeVolume20! - 200 / 105) < 1e-9);
});

test("rejects unsorted or duplicate sessions", () => {
  assert.throws(
    () =>
      summarizeMarketSeries([
        bar("2026-07-16", 5, 6, 4, 5, 100),
        bar("2026-07-16", 5, 6, 4, 5, 100),
      ]),
    /strictly ordered/,
  );
});
