import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("readiness and thesis panel exposes policy, blockers, outcomes, and chain without investment controls", () => {
  const source = readFileSync(
    new URL("../components/readiness-thesis-panel.tsx", import.meta.url),
    "utf8",
  );

  for (const label of [
    "Deterministic readiness",
    "Requested disposition",
    "Final disposition",
    "11 policy checks",
    "Blocking reasons",
    "Required next evidence",
    "Thesis creation outcome",
    "Canonical chain",
    "Provisional branches",
  ]) {
    assert.match(source, new RegExp(label));
  }
  assert.doesNotMatch(
    source,
    /universal score|target price|trade action|position size|share quantity|buy recommendation|sell recommendation/i,
  );
});
