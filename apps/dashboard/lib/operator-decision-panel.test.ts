import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("operator decision panel exposes current state, immutable history, and separate effects", () => {
  const source = readFileSync(
    new URL("../components/operator-decision-panel.tsx", import.meta.url),
    "utf8",
  );

  for (const label of [
    "Operator decisions",
    "Derived current state",
    "Append-only history",
    "Deep-research command",
    "Portfolio-review handoff marker",
    "Research result remains unchanged",
  ]) {
    assert.match(source, new RegExp(label));
  }
  assert.doesNotMatch(
    source,
    /position sizing|share quantity|trade recommendation|place order|portfolio suitability/i,
  );
});
