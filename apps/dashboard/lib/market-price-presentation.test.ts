import assert from "node:assert/strict";
import test from "node:test";

import type { MarketBarContext } from "@iros/types";

import {
  marketDataRecency,
  marketHistoryRows,
  marketPriceFormat,
} from "./market-price-presentation.ts";

function bar(sessionDate: string): MarketBarContext {
  return {
    barId: `bar-${sessionDate}`,
    sessionDate,
    open: 10,
    high: 11,
    low: 9,
    close: 10.5,
    volume: 100,
    dividends: 0,
    stockSplits: 0,
    sessionStatus: "completed",
    barSha256: "a".repeat(64),
  };
}

test("preserves cents for market prices at or above ten dollars", () => {
  assert.deepEqual(marketPriceFormat([12.34, 10.01]), {
    type: "price",
    precision: 2,
    minMove: 0.01,
  });
});

test("presents a bounded newest-first market history without changing source bars", () => {
  const bars = [
    bar("2026-07-18"),
    bar("2026-07-21"),
    bar("2026-07-22"),
  ];

  assert.deepEqual(
    marketHistoryRows(bars, 2).map((row) => row.sessionDate),
    ["2026-07-22", "2026-07-21"],
  );
  assert.deepEqual(
    bars.map((row) => row.sessionDate),
    ["2026-07-18", "2026-07-21", "2026-07-22"],
  );
});

test("flags elapsed-time market retrievals without claiming market-calendar freshness", () => {
  assert.deepEqual(
    marketDataRecency(
      "2026-07-22T20:00:00Z",
      new Date("2026-07-25T08:00:00Z"),
    ),
    {
      state: "refresh_due",
      elapsedHours: 60,
      label: "Retrieved 2d ago",
    },
  );
  assert.deepEqual(
    marketDataRecency(
      "2026-07-25T07:30:00Z",
      new Date("2026-07-25T08:00:00Z"),
    ),
    {
      state: "recent",
      elapsedHours: 0,
      label: "Retrieved under 1h ago",
    },
  );
});
