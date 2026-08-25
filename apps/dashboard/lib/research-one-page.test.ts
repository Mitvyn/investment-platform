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
