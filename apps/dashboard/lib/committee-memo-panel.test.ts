import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("committee memo panel exposes required audit sections without investment actions", () => {
  const source = readFileSync(
    new URL("../components/committee-memo-panel.tsx", import.meta.url),
    "utf8",
  );

  for (const label of [
    "Executive summary",
    "Common ground",
    "Material disagreements",
    "Disputed assumptions",
    "Evidence gaps",
    "Invalidation conditions",
    "Required next evidence",
    "Review trigger",
    "Execution-state disclosure",
    "Validation and retry",
    "Synthesis attempt chronology",
    "Cached input",
    "Cache write",
    "Uncached input",
    "Reasoning",
    "Usage completeness",
    "Estimated cost",
    "Price card",
    "Retry policy",
    "Requested disposition",
  ]) {
    assert.match(source, new RegExp(label));
  }
  assert.match(source, /Evidence IDs/);
  assert.match(source, /Opinion IDs/);
  assert.match(source, /Calculation IDs/);
  assert.doesNotMatch(
    source,
    /target price|trade action|position size|buy|sell/i,
  );
});
