import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("Research Run history reads canonical owner-scoped views without raw provider data", () => {
  const source = readFileSync(
    new URL("./research-run-history.ts", import.meta.url),
    "utf8",
  );

  assert.match(source, /iros_v_research_run_eligibility/);
  assert.match(source, /iros_v_research_run_readiness/);
  assert.match(source, /\.eq\("operator_id", operatorId\)/);
  assert.match(source, /\.eq\("security_id", securityId\)/);
  assert.doesNotMatch(
    source,
    /iros_research_runs"|iros_readiness_gate_results"|raw_request|raw_response|reasoning_content/,
  );
});
