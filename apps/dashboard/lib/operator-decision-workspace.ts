import type {
  OperatorDecisionCurrentState,
  OperatorDecisionHistory,
  OperatorWorkflowCommand,
  PortfolioReviewHandoffMarker,
} from "../../../packages/types/operator-decision.ts";

export type OperatorDecisionData = {
  history: OperatorDecisionHistory | null;
  current: OperatorDecisionCurrentState | null;
  commands: OperatorWorkflowCommand[];
  handoffMarkers: PortfolioReviewHandoffMarker[];
};

function sentenceCase(value: string) {
  const normalized = value.replaceAll("_", " ");
  return `${normalized.slice(0, 1).toUpperCase()}${normalized.slice(1)}`;
}

function presentCommand(command: OperatorWorkflowCommand) {
  return {
    commandId: command.workflow_command_id,
    type: sentenceCase(command.command_type),
    state: sentenceCase(command.command_state),
    policyVersion: command.command_policy_version,
    idempotencyKey: command.idempotency_key,
    createdAt: command.created_at,
  };
}

function presentMarker(marker: PortfolioReviewHandoffMarker) {
  return {
    markerId: marker.portfolio_review_handoff_marker_id,
    thesisStatus: sentenceCase(marker.thesis_status),
    finalSystemDisposition: sentenceCase(marker.final_system_disposition),
    readinessStatus: sentenceCase(marker.readiness_status),
    policyVersion: marker.handoff_policy_version,
    idempotencyKey: marker.idempotency_key,
    createdAt: marker.created_at,
  };
}

export function presentOperatorDecisionWorkspace(data: OperatorDecisionData) {
  if (data.history === null || data.current === null) {
    return {
      kind: "missing" as const,
      title: "Operator decision unavailable",
      description:
        "No append-only operator decision is stored for this thesis chain.",
      history: [],
      current: null,
    };
  }

  const commands = new Map(
    data.commands.map((command) => [command.operator_decision_id, command]),
  );
  const handoffMarkers = new Map(
    data.handoffMarkers.map((marker) => [marker.operator_decision_id, marker]),
  );

  return {
    kind: "ready" as const,
    current: {
      decisionId: data.current.current_operator_decision_id,
      action: sentenceCase(data.current.current_operator_action ?? "none"),
      relationship: sentenceCase(data.current.current_relationship ?? "none"),
      supersessionDepth: data.current.supersession_depth,
      derivedAt: data.current.derived_at,
    },
    history: data.history.events.map((event) => ({
      decisionId: event.operator_decision_id,
      thesisVersionId: event.thesis_version_id,
      committeeResultId: event.committee_result_id,
      readinessGateResultId: event.readiness_gate_result_id,
      systemDisposition: sentenceCase(event.system_disposition),
      action: sentenceCase(event.operator_action),
      relationship: sentenceCase(event.relationship),
      rationale: event.rationale,
      supersedesDecisionId: event.supersedes_operator_decision_id,
      policyVersion: event.decision_policy_version,
      idempotencyKey: event.idempotency_key,
      createdAt: event.created_at,
      command: commands.has(event.operator_decision_id)
        ? presentCommand(commands.get(event.operator_decision_id)!)
        : null,
      handoffMarker: handoffMarkers.has(event.operator_decision_id)
        ? presentMarker(handoffMarkers.get(event.operator_decision_id)!)
        : null,
    })),
  };
}

export type OperatorDecisionPresentation = ReturnType<
  typeof presentOperatorDecisionWorkspace
>;
