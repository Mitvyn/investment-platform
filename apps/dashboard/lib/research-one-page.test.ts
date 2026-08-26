import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
const summary = readFileSync(
  new URL("../components/research-decision-summary.tsx", import.meta.url),
  "utf8",
);
const workspace = `${page}\n${summary}`;

test("Research presents decision summary before one continuous detail workspace", () => {
  const summaryIndex = workspace.indexOf("Decision summary");
  const controlsIndex = workspace.indexOf("Research controls and source ledger");
  const detailIndex = workspace.indexOf("Research details");
  const summaryRenderIndex = page.indexOf("<ResearchDecisionSummary");
  const detailRenderIndex = page.indexOf("<ResearchDetailsHeading");

  assert.ok(summaryIndex >= 0);
  assert.ok(controlsIndex >= 0);
  assert.ok(summaryRenderIndex >= 0);
  assert.ok(detailRenderIndex > controlsIndex);
  assert.ok(detailIndex > summaryIndex);
  assert.match(workspace, /Current quote/);
  assert.match(workspace, /Portfolio position/);
  assert.match(workspace, /Evidence freshness/);
  assert.match(workspace, /Key finding/);
  assert.match(workspace, /Valuation context/);
  assert.match(workspace, /Evidence gaps/);
  assert.match(workspace, /Import, preflight, command state, notebook, and source receipts/);
  assert.doesNotMatch(page, /<ResearchStageRail/);
});

test("Research keeps legacy market and source detail below the summary", () => {
  const summaryRenderIndex = page.indexOf("<ResearchDecisionSummary");
  const detailHeadingIndex = page.indexOf("<ResearchDetailsHeading");
  const marketDetailIndex = page.indexOf('aria-label="Market and source detail"');

  assert.ok(summaryRenderIndex >= 0);
  assert.ok(detailHeadingIndex > summaryRenderIndex);
  assert.ok(marketDetailIndex > detailHeadingIndex);
  assert.match(page.slice(marketDetailIndex), /Market context/);
  assert.match(page.slice(marketDetailIndex), /Source health/);
});

test("Research keeps stale-market recovery and portfolio uncertainty visible in the summary", () => {
  assert.match(page, /Refresh quote/);
  assert.match(page, /Refresh quote above/);
  assert.match(page, /close_price/);
  assert.match(page, /Unknown — portfolio not synced/);
  assert.match(page, /Stored daily context/);
});

test("Research attention values are not clipped before the operator can read them", () => {
  assert.doesNotMatch(summary, /line-clamp-2/);
});

test("Research workspace status reflects the primary MCP connection", () => {
  assert.match(page, /const mcpConnectionState\s*=\s*moomooMcpStatus\.state === "ready" \? "connected"/);
  assert.match(page, /moomooState=\{mcpConnectionState\}/);
  assert.doesNotMatch(page, /moomooState=\{moomooStatus\.state\}/);
});

test("Research decision summary matches dark workspace surfaces", () => {
  assert.match(summary, /bg-card/);
  assert.doesNotMatch(summary, /bg-foreground/);
  assert.doesNotMatch(summary, /text-background/);
});
