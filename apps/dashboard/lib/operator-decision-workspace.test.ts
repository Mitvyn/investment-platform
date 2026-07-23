import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type {
  OperatorDecisionCurrentState,
  OperatorDecisionEvent,
  OperatorDecisionHistory,
  OperatorWorkflowCommand,
  PortfolioReviewHandoffMarker,
} from "../../../packages/types/operator-decision.ts";

import { presentOperatorDecisionWorkspace } from "./operator-decision-workspace.ts";

function fixture(name: string) {
  return JSON.parse(
    readFileSync(
      new URL(
        `../../../tests/fixtures/contracts/operator_decision/v1/${name}`,
        import.meta.url,
      ),
      "utf8",
    ),
  );
}

const event = fixture("decision-ready-handoff.json") as OperatorDecisionEvent;
const marker = fixture(
  "portfolio-review-handoff.json",
) as PortfolioReviewHandoffMarker;

test("presents append-only history, derived current state, and separate effects", () => {
  const history: OperatorDecisionHistory = {
    contract_version: "operator_decision_history.v1",
    operator_id: event.operator_id,
    security_id: event.security_id,
    thesis_contract_id: event.thesis_contract_id,
    events: [event],
    generated_at: event.created_at,
  };
  const current: OperatorDecisionCurrentState = {
    contract_version: "operator_decision_current_state.v1",
    operator_id: event.operator_id,
    security_id: event.security_id,
    thesis_contract_id: event.thesis_contract_id,
    current_operator_decision_id: event.operator_decision_id,
    current_operator_action: event.operator_action,
    current_relationship: event.relationship,
    supersession_depth: 0,
    derived_at: event.created_at,
  };

  const presentation = presentOperatorDecisionWorkspace({
    history,
    current,
    commands: [] as OperatorWorkflowCommand[],
    handoffMarkers: [marker],
  });

  assert.equal(presentation.kind, "ready");
  assert.deepEqual(presentation.current, {
    decisionId: event.operator_decision_id,
    action: "Mark for future portfolio review",
    relationship: "Accept",
    supersessionDepth: 0,
    derivedAt: event.created_at,
  });
  assert.deepEqual(presentation.history[0], {
    decisionId: event.operator_decision_id,
    thesisVersionId: event.thesis_version_id,
    committeeResultId: event.committee_result_id,
    readinessGateResultId: event.readiness_gate_result_id,
    systemDisposition: "Decision ready",
    action: "Mark for future portfolio review",
    relationship: "Accept",
    rationale: event.rationale,
    supersedesDecisionId: null,
    policyVersion: event.decision_policy_version,
    idempotencyKey: event.idempotency_key,
    createdAt: event.created_at,
    command: null,
    handoffMarker: {
      markerId: marker.portfolio_review_handoff_marker_id,
      thesisStatus: "Canonical",
      finalSystemDisposition: "Decision ready",
      readinessStatus: "Passed",
      policyVersion: marker.handoff_policy_version,
      idempotencyKey: marker.idempotency_key,
      createdAt: marker.created_at,
    },
  });
});
