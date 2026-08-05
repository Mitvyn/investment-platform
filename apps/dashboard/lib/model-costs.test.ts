import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("model cost source queries hardened owner-scoped views without provider bodies", () => {
  const source = readFileSync(new URL("./model-costs.ts", import.meta.url), "utf8");

  for (const view of (
    [
      "iros_v_model_cost_budgets",
      "iros_v_model_cost_reservations",
      "iros_v_model_cost_attempts",
    ]
  )) {
    assert.match(source, new RegExp(`from\\(\"${view}\"\\)`));
  }
  assert.ok(source.match(/\.eq\("operator_id", operatorId\)/g)?.length === 3);
  assert.ok(source.match(/\.eq\("research_run_id", researchRunId\)/g)?.length === 3);
  assert.doesNotMatch(
    source,
    /payload|sanitized_request|sanitized_response|reasoning_content|encrypted_content/i,
  );
});
