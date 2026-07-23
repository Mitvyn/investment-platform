"use client";

import type { MarketBarContext } from "@iros/types";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import { marketPriceFormat } from "@/lib/market-price-presentation";

export function MarketPriceChart({ bars }: { bars: MarketBarContext[] }) {
  const containerRef = useRef<HTMLDivElement>(null);

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
    <div
      aria-label="Unadjusted daily price and volume chart"
      className="min-h-[420px] w-full"
      ref={containerRef}
    />
  );
}
