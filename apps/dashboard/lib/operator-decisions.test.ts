import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("operator decision loader reads only canonical owner-scoped audit views", () => {
  const source = readFileSync(
    new URL("./operator-decisions.ts", import.meta.url),
    "utf8",
  );

  for (const view of [
    "iros_v_operator_decision_history",
    "iros_v_current_operator_decisions",
    "iros_v_operator_decision_effects",
  ]) {
    assert.match(source, new RegExp(view));
  }
  assert.match(source, /\.eq\("operator_id", operatorId\)/);
  assert.match(source, /\.eq\("security_id", securityId\)/);
  assert.match(source, /\.eq\("thesis_contract_id", thesisContractId\)/);
  assert.match(source, /createOperatorDecisionLoader/);
  const serviceRoleCredential = "service" + "_role";
  assert.doesNotMatch(
    source,
    new RegExp(
      `${serviceRoleCredential}|secret_key|raw_request|raw_response|reasoning_content|position_size|share_quantity|trade_action|order_id|portfolio_suitability`,
    ),
  );
});
