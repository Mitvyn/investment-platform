import type {
  CatalystContext,
  FinancialMetric,
  MarketContext,
  RiskContext,
  TickerContext,
} from "@iros/types";

import { createClient } from "./supabase/server";

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

type CatalystRow = {
  title: string;
  status: CatalystContext["status"];
  window_start: string;
  window_end: string;
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

type RiskRow = {
  title: string;
  risk_type: RiskContext["riskType"];
  severity: RiskContext["severity"];
  status: RiskContext["status"];
  locator: string;
  passage_text: string;
  passage_sha256: string;
  source_title: string;
  published_at: string;
  source_url: string;
  retrieved_at: string;
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

function mapCatalyst(row: CatalystRow): CatalystContext {
  return {
    title: row.title,
    status: row.status,
    windowStart: row.window_start,
    windowEnd: row.window_end,
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

function mapRisk(row: RiskRow): RiskContext {
  return {
    title: row.title,
    riskType: row.risk_type,
    severity: row.severity,
    status: row.status,
    locator: row.locator,
    passage: row.passage_text,
    passageSha256: row.passage_sha256,
    sourceTitle: row.source_title,
    publishedAt: row.published_at,
    sourceUrl: row.source_url,
    retrievedAt: row.retrieved_at,
  };
}

export async function loadTickerContext(ticker: string): Promise<TickerContext> {
  const supabase = await createClient();
  const normalizedTicker = ticker.toUpperCase();
  const [financialResult, catalystResult, riskResult, marketResult] =
    await Promise.all([
    supabase
      .from("iros_v_financial_health")
      .select(
        "metric_key,metric_label,metric_kind,value,unit,source_period,comparison_period,formula,locator,passage_text,passage_sha256,source_title,published_at,source_url,retrieved_at",
      )
      .eq("ticker", normalizedTicker)
      .order("published_at", { ascending: false }),
    supabase
      .from("iros_v_catalyst_context")
      .select(
        "title,status,window_start,window_end,locator,passage_text,passage_sha256,source_title,published_at,source_url,retrieved_at",
      )
      .eq("ticker", normalizedTicker)
      .order("window_start", { ascending: true })
      .limit(1)
      .maybeSingle(),
    supabase
      .from("iros_v_risk_context")
      .select(
        "title,risk_type,severity,status,locator,passage_text,passage_sha256,source_title,published_at,source_url,retrieved_at",
      )
      .eq("ticker", normalizedTicker)
      .eq("status", "active")
      .limit(1)
      .maybeSingle(),
    supabase
      .from("iros_v_market_context")
      .select(
        "provider,exchange,currency,market_time,close,previous_close,change,percent_change,volume,is_market_open,source_url,retrieved_at",
      )
      .eq("ticker", normalizedTicker)
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
      throw new Error(`Ticker context API failed: ${result.error.message}`);
    }
  }

  const financialRows = (financialResult.data ?? []) as FinancialRow[];
  const latestPublishedAt = financialRows[0]?.published_at;
  return {
    financialMetrics: financialRows
      .filter((row) => row.published_at === latestPublishedAt)
      .map(mapFinancial),
    catalyst: catalystResult.data
      ? mapCatalyst(catalystResult.data as CatalystRow)
      : null,
    risk: riskResult.data ? mapRisk(riskResult.data as RiskRow) : null,
    market: marketResult.data ? mapMarket(marketResult.data as MarketRow) : null,
  };
}
