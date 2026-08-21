import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

const page = readFileSync(
  fileURLToPath(new URL("../app/page.tsx", import.meta.url)),
  "utf8",
);

test("market evidence card renders refresh action, states, and disclaimers", () => {
  assert.match(page, /Refresh market evidence/);
  assert.match(page, /official close, valuation, or trading signal/);
  assert.match(page, /needs authorized MCP discovery first/);
  assert.match(page, /not investment/);
  assert.match(page, /trade signal/);
  assert.match(page, /This security could not be verified against the authenticated security directory\./);
  assert.match(page, /Market evidence is stale/);
  assert.match(page, /cached/);
});

test("market evidence card appears before Research Run preflight", () => {
  const marketEvidenceIndex = page.indexOf("Refresh market evidence");
  const preflightIndex = page.indexOf("Research Run preflight");
  assert.ok(marketEvidenceIndex > -1);
  assert.ok(preflightIndex > -1);
  assert.ok(marketEvidenceIndex < preflightIndex);
});

test("market evidence card never renders a raw tool catalog or provider payload", () => {
  const start = page.indexOf("SectionLabel>Market evidence<");
  const end = page.indexOf("Accepted evidence capture");
  const card = page.slice(start, end);
  assert.doesNotMatch(card, /inputSchema/);
  assert.doesNotMatch(card, /input_schema_sha256/);
  assert.doesNotMatch(card, /tool_count/i);
  assert.doesNotMatch(card, /access_token|bearer/i);
});
