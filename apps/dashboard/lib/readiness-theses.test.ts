import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("readiness and thesis loader reads only canonical owner-scoped audit views", () => {
  const source = readFileSync(
    new URL("./readiness-theses.ts", import.meta.url),
    "utf8",
  );

  for (const view of [
    "iros_v_research_run_readiness",
    "iros_v_research_run_thesis",
    "iros_v_thesis_chains",
  ]) {
    assert.match(source, new RegExp(view));
  }
  assert.match(source, /\.eq\("operator_id", operatorId\)/);
  assert.match(source, /parseReadinessGateResult/);
  assert.match(source, /parseThesisCreationResult/);
  assert.match(source, /parseThesisChain/);
  assert.doesNotMatch(
    source,
    /raw_request|raw_response|reasoning_content|provider_payload|universal_score|target_price|position_size/,
  );
});
