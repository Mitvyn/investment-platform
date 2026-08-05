import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { createOperatorDecisionLoader } from "./operator-decision-loader.ts";

function fixture(path: string) {
  return JSON.parse(
    readFileSync(new URL(`../../../tests/fixtures/contracts/${path}`, import.meta.url), "utf8"),
  );
}

const decision = fixture(
  "operator_decision/v1/decision-ready-handoff.json",
);
const thesis = fixture(
  "readiness_thesis/v1/canonical-thesis.json",
);
const readiness = fixture(
  "readiness_thesis/v1/decision-ready.json",
);
const marker = fixture(
  "operator_decision/v1/portfolio-review-handoff.json",
);
const owner = decision.operator_id as string;
const security = decision.security_id as string;
const contract = decision.thesis_contract_id as string;

test("loads strict append-only history, derived current state, and separate effects by owner tuple", async () => {
  const requested: Array<{ source: string; values: string[] }> = [];
  const history = {
    contract_version: "operator_decision_history.v1",
    operator_id: owner,
    security_id: security,
    thesis_contract_id: contract,
    events: [decision],
    generated_at: decision.created_at,
  };
  const current = {
    contract_version: "operator_decision_current_state.v1",
    operator_id: owner,
    security_id: security,
    thesis_contract_id: contract,
    current_operator_decision_id: decision.operator_decision_id,
    current_operator_action: decision.operator_action,
    current_relationship: decision.relationship,
    supersession_depth: 0,
    derived_at: decision.created_at,
  };
  const load = createOperatorDecisionLoader(
    async (...values) => {
      requested.push({ source: "history", values });
      return [{
        operator_id: owner,
        security_id: security,
        thesis_contract_id: contract,
        canonical_history: history,
      }];
    },
    async (...values) => {
      requested.push({ source: "current", values });
      return [{
        operator_id: owner,
        security_id: security,
        thesis_contract_id: contract,
        current_operator_decision_id: decision.operator_decision_id,
        canonical_current_state: current,
      }];
    },
    async (...values) => {
      requested.push({ source: "effects", values });
      return [{
        operator_id: owner,
        security_id: security,
        thesis_contract_id: contract,
        operator_decision_id: decision.operator_decision_id,
        thesis_version_id: decision.thesis_version_id,
        committee_result_id: decision.committee_result_id,
        readiness_gate_result_id: decision.readiness_gate_result_id,
        canonical_decision: decision,
        canonical_thesis: thesis,
        canonical_readiness: readiness,
        canonical_command: null,
        canonical_marker: marker,
      }];
    },
  );

  const result = await load(owner, security, contract);

  assert.deepEqual(result, {
    history,
    current,
    commands: [],
    handoffMarkers: [marker],
  });
  assert.deepEqual(requested, [
    { source: "history", values: [owner, security, contract] },
    { source: "current", values: [owner, security, contract] },
    { source: "effects", values: [owner, security, contract] },
  ]);
});

test("loads personal-research decisions without portfolio handoff markers", async () => {
  const personalContract =
    "biotech_moonshot_catalyst_personal_research_v1";
  const personalDecision = {
    ...decision,
    thesis_contract_id: personalContract,
    operator_action: "no_action",
    relationship: "defer",
    rationale: "Reviewed for personal research only.",
    idempotency_key: "personal-research:no-action",
  };
  const personalThesis = {
    ...thesis,
    thesis_contract_id: personalContract,
    question_type_version:
      "biotech_moonshot_catalyst_personal_research_assessment.v1",
    workflow_config_version:
      "biotech-moonshot-catalyst-personal-research-v1",
    readiness_gate_policy_version: "biotech-personal-readiness.v1",
  };
  const personalReadiness = {
    ...readiness,
    thesis_contract_id: personalContract,
    gate_policy_version: "biotech-personal-readiness.v1",
  };
  const history = {
    contract_version: "operator_decision_history.v1",
    operator_id: owner,
    security_id: security,
    thesis_contract_id: personalContract,
    events: [personalDecision],
    generated_at: personalDecision.created_at,
  };
  const current = {
    contract_version: "operator_decision_current_state.v1",
    operator_id: owner,
    security_id: security,
    thesis_contract_id: personalContract,
    current_operator_decision_id: personalDecision.operator_decision_id,
    current_operator_action: personalDecision.operator_action,
    current_relationship: personalDecision.relationship,
    supersession_depth: 0,
    derived_at: personalDecision.created_at,
  };
  const load = createOperatorDecisionLoader(
    async () => [{
      operator_id: owner,
      security_id: security,
      thesis_contract_id: personalContract,
      canonical_history: history,
    }],
    async () => [{
      operator_id: owner,
      security_id: security,
      thesis_contract_id: personalContract,
      current_operator_decision_id: personalDecision.operator_decision_id,
      canonical_current_state: current,
    }],
    async () => [{
      operator_id: owner,
      security_id: security,
      thesis_contract_id: personalContract,
      operator_decision_id: personalDecision.operator_decision_id,
      thesis_version_id: personalDecision.thesis_version_id,
      committee_result_id: personalDecision.committee_result_id,
      readiness_gate_result_id: personalDecision.readiness_gate_result_id,
      canonical_decision: personalDecision,
      canonical_thesis: personalThesis,
      canonical_readiness: personalReadiness,
      canonical_command: null,
      canonical_marker: null,
    }],
  );

  const result = await load(owner, security, personalContract);

  assert.equal(result.history?.thesis_contract_id, personalContract);
  assert.equal(result.current?.current_operator_action, "no_action");
  assert.deepEqual(result.handoffMarkers, []);
});
