import type {
  FinancialMetric,
  MarketContext,
  MarketSeriesContext,
  TickerContext,
} from "@iros/types";

import { createClient } from "./supabase/server";
import {
  selectRelevantCatalyst,
  type CatalystCandidate,
  selectHighestPriorityActiveRisk,
  type RiskCandidate,
} from "./context-selection";
import { marketSeriesUnavailableReason } from "./market-series-load-error";

type FinancialRow = {
  metric_key: string;
  metric_label: string;
  metric_kind: FinancialMetric["metricKind"];
  value: number | string;
  unit: FinancialMetric["unit"];
  source_period: string;
  comparison_period: string | null;
  formula: string | null;
  locator: string;
  passage_text: string;
  passage_sha256: string;
  source_title: string;
  published_at: string;
  source_url: string;
  retrieved_at: string;
};

type MarketRow = {
  provider: MarketContext["provider"];
  exchange: string;
  currency: string;
  market_time: string;
  close: number | string;
  previous_close: number | string;
  change: number | string;
  percent_change: number | string;
  volume: number | string | null;
  is_market_open: boolean;
  source_url: string;
  retrieved_at: string;
};

type MarketSeriesRow = {
  security_id: string;
  series_id: string;
  ticker: string;
  provider: MarketSeriesContext["provider"];
  provider_config_version: string;
  exchange: string;
  currency: string;
  interval: MarketSeriesContext["interval"];
  adjustment_status: MarketSeriesContext["adjustmentStatus"];
  session_start: string;
  session_end: string;
  source_url: string;
  retrieved_at: string;
  response_sha256: string;
  bar_id: string;
  session_date: string;
  open: number | string;
  high: number | string;
  low: number | string;
  close: number | string;
  volume: number | string | null;
  dividends: number | string;
  stock_splits: number | string;
  session_status: "completed";
  bar_sha256: string;
};

export type MarketSeriesLoadResult = {
  series: MarketSeriesContext | null;
  unavailableReason: string | null;
};

function mapFinancial(row: FinancialRow): FinancialMetric {
  return {
    metricKey: row.metric_key,
    metricLabel: row.metric_label,
    metricKind: row.metric_kind,
    value: Number(row.value),
    unit: row.unit,
    sourcePeriod: row.source_period,
    comparisonPeriod: row.comparison_period,
    formula: row.formula,
    locator: row.locator,
    passage: row.passage_text,
    passageSha256: row.passage_sha256,
    sourceTitle: row.source_title,
    publishedAt: row.published_at,
    sourceUrl: row.source_url,
    retrievedAt: row.retrieved_at,
  };
}

function mapMarket(row: MarketRow): MarketContext {
  return {
    provider: row.provider,
    exchange: row.exchange,
    currency: row.currency,
    marketTime: row.market_time,
    close: Number(row.close),
    previousClose: Number(row.previous_close),
    change: Number(row.change),
    percentChange: Number(row.percent_change),
    volume: row.volume === null ? null : Number(row.volume),
    isMarketOpen: row.is_market_open,
    sourceUrl: row.source_url,
    retrievedAt: row.retrieved_at,
  };
}

export async function loadTickerContext(securityId: string): Promise<TickerContext> {
  const supabase = await createClient();
  const asOfDate = new Date().toISOString().slice(0, 10);
  const [financialResult, catalystResult, riskResult, marketResult] =
    await Promise.all([
    supabase
      .from("iros_v_security_financial_health")
      .select(
        "security_id,metric_key,metric_label,metric_kind,value,unit,source_period,comparison_period,formula,locator,passage_text,passage_sha256,source_title,published_at,source_url,retrieved_at",
      )
      .eq("security_id", securityId)
      .order("published_at", { ascending: false }),
    supabase
      .from("iros_v_security_catalyst_context")
      .select(
        "security_id,title,status,window_start,window_end,locator,passage_text,passage_sha256,source_title,published_at,source_url,retrieved_at",
      )
      .eq("security_id", securityId)
      .in("status", ["expected", "delayed"])
      .gte("window_end", asOfDate)
      .order("window_start", { ascending: true }),
    supabase
      .from("iros_v_security_risk_context")
      .select(
        "security_id,title,risk_type,severity,status,locator,passage_text,passage_sha256,source_title,published_at,source_url,retrieved_at",
      )
      .eq("security_id", securityId)
      .eq("status", "active"),
    supabase
      .from("iros_v_security_market_context")
      .select(
        "security_id,provider,exchange,currency,market_time,close,previous_close,change,percent_change,volume,is_market_open,source_url,retrieved_at",
      )
      .eq("security_id", securityId)
      .order("market_time", { ascending: false })
      .limit(1)
      .maybeSingle(),
    ]);

  for (const result of [
    financialResult,
    catalystResult,
    riskResult,
    marketResult,
  ]) {
    if (result.error) {
      if (result.error.code === "42P01" || result.error.code === "PGRST205") {
        return {
          financialMetrics: [],
          catalyst: null,
          risk: null,
          market: null,
          marketSeries: null,
        };
      }
      throw new Error(`Ticker context API failed: ${result.error.message}`);
    }
  }

  const financialRows = (financialResult.data ?? []) as FinancialRow[];
  const latestPublishedAt = financialRows[0]?.published_at;
  return {
    financialMetrics: financialRows
      .filter((row) => row.published_at === latestPublishedAt)
      .map(mapFinancial),
    catalyst: selectRelevantCatalyst(
      (catalystResult.data ?? []) as CatalystCandidate[],
      asOfDate,
    ),
    risk: selectHighestPriorityActiveRisk(
      (riskResult.data ?? []) as RiskCandidate[],
    ),
    market: marketResult.data ? mapMarket(marketResult.data as MarketRow) : null,
    marketSeries: null,
  };
}

export async function loadMarketSeries(
  securityId: string,
): Promise<MarketSeriesLoadResult> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_market_series")
    .select(
      "security_id,series_id,ticker,provider,provider_config_version,exchange,currency,interval,adjustment_status,session_start,session_end,source_url,retrieved_at,response_sha256,bar_id,session_date,open,high,low,close,volume,dividends,stock_splits,session_status,bar_sha256",
    )
    .eq("security_id", securityId)
    .order("session_date", { ascending: true });

  if (error) {
    return {
      series: null,
      unavailableReason: marketSeriesUnavailableReason(error),
    };
  }
  const rows = (data ?? []) as MarketSeriesRow[];
  if (!rows.length) return { series: null, unavailableReason: null };
  const first = rows[0];
  if (
    rows.some(
      (row) =>
        row.security_id !== first.security_id ||
        row.series_id !== first.series_id ||
        row.response_sha256 !== first.response_sha256,
    )
  ) {
    throw new Error("Market series API returned mixed immutable series");
  }
  return {
    series: {
      securityId: first.security_id,
      seriesId: first.series_id,
      ticker: first.ticker,
      provider: first.provider,
      providerConfigVersion: first.provider_config_version,
      exchange: first.exchange,
      currency: first.currency,
      interval: first.interval,
      adjustmentStatus: first.adjustment_status,
      sessionStart: first.session_start,
      sessionEnd: first.session_end,
      sourceUrl: first.source_url,
      retrievedAt: first.retrieved_at,
      responseSha256: first.response_sha256,
      bars: rows.map((row) => ({
        barId: row.bar_id,
        sessionDate: row.session_date,
        open: Number(row.open),
        high: Number(row.high),
        low: Number(row.low),
        close: Number(row.close),
        volume: row.volume === null ? null : Number(row.volume),
        dividends: Number(row.dividends),
        stockSplits: Number(row.stock_splits),
        sessionStatus: row.session_status,
        barSha256: row.bar_sha256,
      })),
    },
    unavailableReason: null,
  };
}
