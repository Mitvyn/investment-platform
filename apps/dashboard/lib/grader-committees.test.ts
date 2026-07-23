import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("committee workspace loader reads owner-scoped canonical view without raw provider bodies", () => {
  const source = readFileSync(
    new URL("./grader-committees.ts", import.meta.url),
    "utf8",
  );

  assert.match(source, /iros_v_research_run_committees/);
  assert.match(source, /operator_id,research_run_id,committee_result_id,canonical_committee/);
  assert.doesNotMatch(
    source,
    /iros_model_attempt_payloads|raw_request|raw_response|reasoning_content/,
  );
});
