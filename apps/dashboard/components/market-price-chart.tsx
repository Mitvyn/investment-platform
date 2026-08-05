"use client";

import type { MarketBarContext } from "@iros/types";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  type Time,
} from "lightweight-charts";
import { useEffect, useId, useRef } from "react";

import {
  marketDataRecency,
  marketHistoryRows,
  marketPriceFormat,
} from "@/lib/market-price-presentation";

type MarketPriceChartProps = {
  bars: MarketBarContext[];
  currency: string;
  recencyCheckedAt: string;
  retrievedAt: string;
  sessionEnd: string;
};

function formatPrice(value: number, currency: string) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: value < 1 ? 4 : 2,
  }).format(value);
}

function formatVolume(value: number | null) {
  return value === null
    ? "Unavailable"
    : new Intl.NumberFormat("en-US").format(value);
}

export function MarketPriceChart({
  bars,
  currency,
  recencyCheckedAt,
  retrievedAt,
  sessionEnd,
}: MarketPriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const noteId = useId();
  const historyRows = marketHistoryRows(bars);
  const recency = marketDataRecency(retrievedAt, new Date(recencyCheckedAt));

  useEffect(() => {
    const container = containerRef.current;
    if (!container || bars.length === 0) return;

    const chart = createChart(container, {
      autoSize: true,
      height: 420,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#94a3b8",
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "rgba(148, 163, 184, 0.10)" },
        horzLines: { color: "rgba(148, 163, 184, 0.10)" },
      },
      rightPriceScale: { borderColor: "rgba(148, 163, 184, 0.18)" },
      timeScale: { borderColor: "rgba(148, 163, 184, 0.18)" },
    });
    const candles = chart.addSeries(CandlestickSeries, {
      priceFormat: marketPriceFormat(bars.flatMap((bar) => [bar.open, bar.high, bar.low, bar.close])),
      upColor: "#06b6d4",
      downColor: "#ef4444",
      borderUpColor: "#06b6d4",
      borderDownColor: "#ef4444",
      wickUpColor: "#06b6d4",
      wickDownColor: "#ef4444",
    });
    candles.setData(
      bars.map((bar) => ({
        time: bar.sessionDate as Time,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      })),
    );
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    volume.priceScale().applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    });
    volume.setData(
      bars
        .filter((bar) => bar.volume !== null)
        .map((bar) => ({
          time: bar.sessionDate as Time,
          value: bar.volume!,
          color:
            bar.close >= bar.open
              ? "rgba(6, 182, 212, 0.40)"
              : "rgba(239, 68, 68, 0.38)",
        })),
    );
    chart.timeScale().fitContent();

    return () => chart.remove();
  }, [bars]);

  return (
    <>
      <div
        aria-describedby={noteId}
        aria-label="Unadjusted daily price and volume chart"
        className="min-h-[420px] w-full"
        ref={containerRef}
        role="img"
      />
      <div
        className={`mt-4 rounded-lg border px-4 py-3 text-sm ${
          recency.state === "refresh_due"
            ? "border-warning/35 bg-warning-muted text-warning-muted-foreground"
            : "border-border bg-muted/30 text-muted-foreground"
        }`}
        id={noteId}
      >
        <p>
          Last stored session: <time dateTime={sessionEnd}>{sessionEnd}</time>.{" "}
          {recency.label}.
        </p>
        {recency.state === "refresh_due" ? (
          <p className="mt-1">
            Refresh may be needed. Recency warning uses elapsed retrieval time,
            not exchange-calendar validation.
          </p>
        ) : null}
      </div>
      <details className="mt-4 rounded-lg border border-border">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
          View {historyRows.length} recent OHLCV sessions
        </summary>
        <div className="overflow-x-auto border-t border-border">
          <table className="w-full min-w-[48rem] text-left text-sm">
            <caption className="sr-only">
              {historyRows.length} most recent stored completed sessions, newest
              first. Prices in {currency}. No interpolation.
            </caption>
            <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-3" scope="col">
                  Session
                </th>
                <th className="px-4 py-3 text-right" scope="col">
                  Open
                </th>
                <th className="px-4 py-3 text-right" scope="col">
                  High
                </th>
                <th className="px-4 py-3 text-right" scope="col">
                  Low
                </th>
                <th className="px-4 py-3 text-right" scope="col">
                  Close
                </th>
                <th className="px-4 py-3 text-right" scope="col">
                  Volume
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border font-mono tabular-nums">
              {historyRows.map((bar) => (
                <tr key={bar.barId}>
                  <th className="px-4 py-3 font-medium" scope="row">
                    <time dateTime={bar.sessionDate}>{bar.sessionDate}</time>
                  </th>
                  <td className="px-4 py-3 text-right">
                    {formatPrice(bar.open, currency)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {formatPrice(bar.high, currency)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {formatPrice(bar.low, currency)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {formatPrice(bar.close, currency)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {formatVolume(bar.volume)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
