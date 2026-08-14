import assert from "node:assert/strict";
import test from "node:test";

import type { MarketBarContext } from "@iros/types";

import {
  availableMarketRanges,
  marketDataRecency,
  marketHistoryRows,
  marketPriceFormat,
  marketVisibleRange,
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

function sessionsBetween(start: string, end: string): MarketBarContext[] {
  const bars: MarketBarContext[] = [];
  const cursor = new Date(`${start}T00:00:00Z`);
  const last = new Date(`${end}T00:00:00Z`);
  while (cursor <= last) {
    const day = cursor.getUTCDay();
    if (day !== 0 && day !== 6) bars.push(bar(cursor.toISOString().slice(0, 10)));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return bars;
}

test("anchors every chart range to the newest stored session, not to today", () => {
  const bars = sessionsBetween("2025-07-23", "2026-07-22");
  assert.deepEqual(marketVisibleRange(bars, "3m"), {
    from: "2026-04-22",
    to: "2026-07-22",
    barCount: bars.filter((item) => item.sessionDate >= "2026-04-22").length,
  });
  assert.deepEqual(marketVisibleRange(bars, "ytd"), {
    from: "2026-01-01",
    to: "2026-07-22",
    barCount: bars.filter((item) => item.sessionDate >= "2026-01-01").length,
  });
});

test("clamps a range wider than stored history to the first stored session", () => {
  const bars = sessionsBetween("2026-06-01", "2026-07-22");
  const resolved = marketVisibleRange(bars, "1y");
  assert.equal(resolved?.from, "2026-06-01");
  assert.equal(resolved?.to, "2026-07-22");
  assert.equal(resolved?.barCount, bars.length);
});

test("offers no range controls when no sessions are stored", () => {
  assert.equal(marketVisibleRange([], "1m"), null);
  assert.deepEqual(availableMarketRanges([]), []);
});

test("hides ranges that would collapse onto the full stored history", () => {
  const threeMonths = availableMarketRanges(
    sessionsBetween("2026-04-22", "2026-07-22"),
  );
  assert.ok(threeMonths.includes("1m"), "1M genuinely narrows three months");
  assert.ok(threeMonths.includes("all"));
  assert.ok(
    !threeMonths.includes("6m"),
    "6M exceeds stored history and duplicates All",
  );
  assert.ok(
    !threeMonths.includes("1y"),
    "1Y exceeds stored history and duplicates All",
  );

  const threeWeeks = availableMarketRanges(
    sessionsBetween("2026-07-01", "2026-07-22"),
  );
  assert.deepEqual(
    threeWeeks,
    ["all"],
    "three weeks of sessions support no narrower range",
  );
});
