import type { CatalystContext, RiskContext } from "@iros/types";

export type CatalystCandidate = {
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

export type RiskCandidate = {
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

function mapCatalyst(row: CatalystCandidate): CatalystContext {
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

export function selectRelevantCatalyst(
  rows: readonly CatalystCandidate[],
  asOfDate: string,
): CatalystContext | null {
  const selected = rows
    .filter(
      (row) =>
        (row.status === "expected" || row.status === "delayed") &&
        row.window_end >= asOfDate,
    )
    .toSorted(
      (left, right) =>
        left.window_start.localeCompare(right.window_start) ||
        left.window_end.localeCompare(right.window_end) ||
        right.published_at.localeCompare(left.published_at) ||
        left.title.localeCompare(right.title) ||
        left.passage_sha256.localeCompare(right.passage_sha256) ||
        left.source_url.localeCompare(right.source_url),
    )[0];

  return selected ? mapCatalyst(selected) : null;
}

const RISK_SEVERITY_PRIORITY: Record<RiskContext["severity"], number> = {
  high: 3,
  medium: 2,
  low: 1,
};

export function selectHighestPriorityActiveRisk(
  rows: readonly RiskCandidate[],
): RiskContext | null {
  const selected = rows
    .filter((row) => row.status === "active")
    .toSorted(
      (left, right) =>
        RISK_SEVERITY_PRIORITY[right.severity] -
          RISK_SEVERITY_PRIORITY[left.severity] ||
        right.published_at.localeCompare(left.published_at) ||
        left.title.localeCompare(right.title) ||
        left.risk_type.localeCompare(right.risk_type) ||
        left.passage_sha256.localeCompare(right.passage_sha256) ||
        left.source_url.localeCompare(right.source_url),
    )[0];

  return selected
    ? {
        title: selected.title,
        riskType: selected.risk_type,
        severity: selected.severity,
        status: selected.status,
        locator: selected.locator,
        passage: selected.passage_text,
        passageSha256: selected.passage_sha256,
        sourceTitle: selected.source_title,
        publishedAt: selected.published_at,
        sourceUrl: selected.source_url,
        retrievedAt: selected.retrieved_at,
      }
    : null;
}
