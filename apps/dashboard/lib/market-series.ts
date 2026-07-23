import type { MarketBarContext } from "@iros/types";

export type MarketSeriesSummary = {
  latest: MarketBarContext;
  previousClose: number;
  change: number;
  percentChange: number;
  periodHigh: number;
  periodLow: number;
  averageVolume20: number | null;
  relativeVolume20: number | null;
  sessionCount: number;
};

function roundMetric(value: number) {
  return Math.round(value * 1_000_000_000_000) / 1_000_000_000_000;
}

export function summarizeMarketSeries(
  bars: MarketBarContext[],
): MarketSeriesSummary {
  if (bars.length < 2) {
    throw new Error("market series requires two completed sessions");
  }
  for (let index = 1; index < bars.length; index += 1) {
    if (bars[index - 1].sessionDate >= bars[index].sessionDate) {
      throw new Error("market sessions must be strictly ordered");
    }
  }

  const latest = bars.at(-1)!;
  const previousClose = bars.at(-2)!.close;
  const change = roundMetric(latest.close - previousClose);
  const volumes = bars.slice(-20).map((bar) => bar.volume);
  const hasCompleteVolumeWindow =
    volumes.length === 20 && volumes.every((volume) => volume !== null);
  const averageVolume20 = hasCompleteVolumeWindow
    ? roundMetric(
        (volumes as number[]).reduce((total, volume) => total + volume, 0) /
          volumes.length,
      )
    : null;

  return {
    latest,
    previousClose,
    change,
    percentChange: roundMetric((change / previousClose) * 100),
    periodHigh: Math.max(...bars.map((bar) => bar.high)),
    periodLow: Math.min(...bars.map((bar) => bar.low)),
    averageVolume20,
    relativeVolume20:
      averageVolume20 === null || latest.volume === null
        ? null
        : roundMetric(latest.volume / averageVolume20),
    sessionCount: bars.length,
  };
}
