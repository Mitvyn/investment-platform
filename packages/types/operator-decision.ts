import type { ResearchDisposition } from "./committee-memo.ts";
import type {
  ReadinessGateResult,
  ThesisVersion,
} from "./readiness-thesis.ts";

export const OPERATOR_ACTIONS = Object.freeze([
  "dismiss",
  "monitor",
  "request_deep_research",
  "mark_for_future_portfolio_review",
  "no_action",
] as const);

export type OperatorAction = (typeof OPERATOR_ACTIONS)[number];
export type OperatorDecisionRelationship = "accept" | "override" | "defer";

export type OperatorDecisionEvent = {
  contract_version: "operator_decision_event.v1";
  operator_decision_id: string;
  operator_id: string;
  security_id: string;
  thesis_contract_id: "biotech_moonshot_catalyst_assessment";
  thesis_version_id: string;
  committee_result_id: string;
  readiness_gate_result_id: string;
  system_disposition: ResearchDisposition;
  operator_action: OperatorAction;
  relationship: OperatorDecisionRelationship;
  rationale: string;
  supersedes_operator_decision_id: string | null;
  decision_policy_version: "operator_decision_policy.v1";
  idempotency_key: string;
  created_at: string;
};

export type OperatorDecisionValidationContext = {
  thesisVersion: ThesisVersion;
  readinessResult: ReadinessGateResult;
};

export type OperatorDecisionHistory = {
  contract_version: "operator_decision_history.v1";
  operator_id: string;
  security_id: string;
  thesis_contract_id: "biotech_moonshot_catalyst_assessment";
  events: OperatorDecisionEvent[];
  generated_at: string;
};

export type OperatorDecisionCurrentState = {
  contract_version: "operator_decision_current_state.v1";
  operator_id: string;
  security_id: string;
  thesis_contract_id: "biotech_moonshot_catalyst_assessment";
  current_operator_decision_id: string | null;
  current_operator_action: OperatorAction | null;
  current_relationship: OperatorDecisionRelationship | null;
  supersession_depth: number;
  derived_at: string;
};

export type OperatorDecisionHistoryValidationContext =
  | OperatorDecisionValidationContext
  | readonly OperatorDecisionValidationContext[];

export type OperatorWorkflowCommand = {
  contract_version: "operator_workflow_command.v1";
  workflow_command_id: string;
  operator_decision_id: string;
  operator_id: string;
  security_id: string;
  thesis_contract_id: "biotech_moonshot_catalyst_assessment";
  thesis_version_id: string;
  committee_result_id: string;
  readiness_gate_result_id: string;
  command_type: "create_research_request";
  command_policy_version: "operator_workflow_command_policy.v1";
  idempotency_key: string;
  command_state: "pending";
  created_at: string;
};

export type OperatorWorkflowCommandValidationContext = {
  decision: OperatorDecisionEvent;
};

export type PortfolioReviewHandoffMarker = {
  contract_version: "portfolio_review_handoff_marker.v1";
  portfolio_review_handoff_marker_id: string;
  operator_decision_id: string;
  operator_id: string;
  security_id: string;
  thesis_contract_id: "biotech_moonshot_catalyst_assessment";
  thesis_version_id: string;
  committee_result_id: string;
  readiness_gate_result_id: string;
  thesis_status: "canonical";
  final_system_disposition: "decision_ready";
  readiness_status: "passed";
  handoff_policy_version: "portfolio_review_handoff_policy.v1";
  idempotency_key: string;
  created_at: string;
};

export type PortfolioReviewHandoffValidationContext = {
  decision: OperatorDecisionEvent;
  thesisVersion: ThesisVersion;
  readinessResult: ReadinessGateResult;
};

export type IdempotentReplayResolution<T> = {
  outcome: "created" | "reused";
  value: T;
};

const EVENT_KEYS = [
  "contract_version",
  "operator_decision_id",
  "operator_id",
  "security_id",
  "thesis_contract_id",
  "thesis_version_id",
  "committee_result_id",
  "readiness_gate_result_id",
  "system_disposition",
  "operator_action",
  "relationship",
  "rationale",
  "supersedes_operator_decision_id",
  "decision_policy_version",
  "idempotency_key",
  "created_at",
] as const;
const HISTORY_KEYS = [
  "contract_version",
  "operator_id",
  "security_id",
  "thesis_contract_id",
  "events",
  "generated_at",
] as const;
const COMMAND_KEYS = [
  "contract_version",
  "workflow_command_id",
  "operator_decision_id",
  "operator_id",
  "security_id",
  "thesis_contract_id",
  "thesis_version_id",
  "committee_result_id",
  "readiness_gate_result_id",
  "command_type",
  "command_policy_version",
  "idempotency_key",
  "command_state",
  "created_at",
] as const;
const HANDOFF_KEYS = [
  "contract_version",
  "portfolio_review_handoff_marker_id",
  "operator_decision_id",
  "operator_id",
  "security_id",
  "thesis_contract_id",
  "thesis_version_id",
  "committee_result_id",
  "readiness_gate_result_id",
  "thesis_status",
  "final_system_disposition",
  "readiness_status",
  "handoff_policy_version",
  "idempotency_key",
  "created_at",
] as const;

const DISPOSITIONS = [
  "reject",
  "monitor",
  "deep_research",
  "decision_ready",
] as const;

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError(`invalid ${label}`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
  label: string,
) {
  const actual = Object.keys(value).sort();
  const keys = [...expected].sort();
  if (
    actual.length !== keys.length ||
    actual.some((key, index) => key !== keys[index])
  ) {
    throw new TypeError(`invalid ${label} fields`);
  }
}

function nonEmptyString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new TypeError(`invalid ${label}`);
  }
  return value;
}

function stringValue(value: unknown, label: string): string {
  if (typeof value !== "string") {
    throw new TypeError(`invalid ${label}`);
  }
  return value;
}

function uuid(value: unknown, label: string): string {
  const candidate = nonEmptyString(value, label);
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      candidate,
    )
  ) {
    throw new TypeError(`invalid ${label}`);
  }
  return candidate;
}

function nullableUuid(value: unknown, label: string): string | null {
  return value === null ? null : uuid(value, label);
}

function timestamp(value: unknown, label: string): string {
  const candidate = nonEmptyString(value, label);
  if (
    !/(?:z|[+-]\d{2}:\d{2})$/i.test(candidate) ||
    Number.isNaN(Date.parse(candidate))
  ) {
    throw new TypeError(`invalid ${label}`);
  }
  return candidate;
}

function enumValue<const T extends readonly string[]>(
  value: unknown,
  allowed: T,
  label: string,
): T[number] {
  if (typeof value !== "string" || !allowed.includes(value)) {
    throw new TypeError(`invalid ${label}`);
  }
  return value as T[number];
}

export function deriveOperatorDecisionRelationship(
  systemDisposition: ResearchDisposition,
  operatorAction: OperatorAction,
): OperatorDecisionRelationship {
  if (operatorAction === "no_action") {
    return "defer";
  }
  const acceptedAction: Record<ResearchDisposition, OperatorAction> = {
    reject: "dismiss",
    monitor: "monitor",
    deep_research: "request_deep_research",
    decision_ready: "mark_for_future_portfolio_review",
  };
  return acceptedAction[systemDisposition] === operatorAction
    ? "accept"
    : "override";
}

function validateUpstream(
  event: Record<string, unknown>,
  context: OperatorDecisionValidationContext,
) {
  const thesis = context.thesisVersion;
  const readiness = context.readinessResult;
  if (
    event.operator_id !== thesis.operator_id ||
    event.operator_id !== readiness.operator_id ||
    event.security_id !== thesis.security_id ||
    event.security_id !== readiness.security_id ||
    event.thesis_contract_id !== thesis.thesis_contract_id ||
    event.thesis_contract_id !== readiness.thesis_contract_id ||
    event.thesis_version_id !== thesis.thesis_version_id ||
    event.committee_result_id !== thesis.committee_result_id ||
    event.committee_result_id !== readiness.committee_result_id ||
    event.readiness_gate_result_id !== thesis.readiness_gate_result_id ||
    event.readiness_gate_result_id !== readiness.readiness_gate_result_id ||
    event.system_disposition !== thesis.final_disposition ||
    event.system_disposition !== readiness.final_disposition
  ) {
    throw new TypeError("operator decision does not match upstream research");
  }
}

export function parseOperatorDecisionEvent(
  value: unknown,
  context: OperatorDecisionValidationContext,
): OperatorDecisionEvent {
  const event = record(value, "operator decision event");
  exactKeys(event, EVENT_KEYS, "operator decision event");

  if (event.contract_version !== "operator_decision_event.v1") {
    throw new TypeError("invalid operator decision contract version");
  }
  uuid(event.operator_decision_id, "operator decision id");
  uuid(event.operator_id, "operator id");
  uuid(event.security_id, "security id");
  if (event.thesis_contract_id !== "biotech_moonshot_catalyst_assessment") {
    throw new TypeError("invalid thesis contract id");
  }
  uuid(event.thesis_version_id, "thesis version id");
  uuid(event.committee_result_id, "committee result id");
  uuid(event.readiness_gate_result_id, "readiness gate result id");
  const disposition = enumValue(
    event.system_disposition,
    DISPOSITIONS,
    "system disposition",
  );
  const action = enumValue(event.operator_action, OPERATOR_ACTIONS, "operator action");
  const relationship = enumValue(
    event.relationship,
    ["accept", "override", "defer"] as const,
    "operator decision relationship",
  );
  if (relationship !== deriveOperatorDecisionRelationship(disposition, action)) {
    throw new TypeError("operator decision relationship is not policy-derived");
  }
  const rationale = stringValue(event.rationale, "operator decision rationale");
  if (relationship === "override" && rationale.trim().length === 0) {
    throw new TypeError("operator override requires rationale");
  }
  nullableUuid(event.supersedes_operator_decision_id, "superseded decision id");
  if (event.decision_policy_version !== "operator_decision_policy.v1") {
    throw new TypeError("invalid operator decision policy version");
  }
  nonEmptyString(event.idempotency_key, "operator decision idempotency key");
  timestamp(event.created_at, "operator decision creation time");
  validateUpstream(event, context);
  return value as OperatorDecisionEvent;
}

function upstreamForEvent(
  event: Record<string, unknown>,
  context: OperatorDecisionHistoryValidationContext,
): OperatorDecisionValidationContext {
  const candidates = Array.isArray(context) ? context : [context];
  const found = candidates.find(
    (candidate) =>
      candidate.thesisVersion.thesis_version_id === event.thesis_version_id &&
      candidate.readinessResult.readiness_gate_result_id ===
        event.readiness_gate_result_id,
  );
  if (!found) {
    throw new TypeError("operator decision upstream research is unavailable");
  }
  return found;
}

export function parseOperatorDecisionHistory(
  value: unknown,
  context: OperatorDecisionHistoryValidationContext,
): OperatorDecisionHistory {
  const history = record(value, "operator decision history");
  exactKeys(history, HISTORY_KEYS, "operator decision history");
  if (history.contract_version !== "operator_decision_history.v1") {
    throw new TypeError("invalid operator decision history contract version");
  }
  const operatorId = uuid(history.operator_id, "operator id");
  const securityId = uuid(history.security_id, "security id");
  if (history.thesis_contract_id !== "biotech_moonshot_catalyst_assessment") {
    throw new TypeError("invalid thesis contract id");
  }
  if (!Array.isArray(history.events)) {
    throw new TypeError("invalid operator decision history events");
  }

  const parsed = history.events.map((event, index) => {
    const raw = record(event, `operator decision history event ${index}`);
    const decision = parseOperatorDecisionEvent(
      event,
      upstreamForEvent(raw, context),
    );
    if (
      decision.operator_id !== operatorId ||
      decision.security_id !== securityId ||
      decision.thesis_contract_id !== history.thesis_contract_id
    ) {
      throw new TypeError("operator decision history ownership mismatch");
    }
    return decision;
  });

  const ids = new Set<string>();
  const idempotencyKeys = new Set<string>();
  for (const [index, decision] of parsed.entries()) {
    if (ids.has(decision.operator_decision_id)) {
      throw new TypeError("duplicate operator decision id");
    }
    if (idempotencyKeys.has(decision.idempotency_key)) {
      throw new TypeError("duplicate operator decision idempotency key");
    }
    ids.add(decision.operator_decision_id);
    idempotencyKeys.add(decision.idempotency_key);
    const previous = parsed[index - 1];
    if (
      (index === 0 && decision.supersedes_operator_decision_id !== null) ||
      (index > 0 &&
        decision.supersedes_operator_decision_id !==
          previous.operator_decision_id)
    ) {
      throw new TypeError("invalid operator decision supersession chain");
    }
    if (
      previous &&
      Date.parse(decision.created_at) < Date.parse(previous.created_at)
    ) {
      throw new TypeError("operator decision history is not chronological");
    }
  }
  const generatedAt = timestamp(history.generated_at, "history generation time");
  const latest = parsed.at(-1);
  if (latest && Date.parse(generatedAt) < Date.parse(latest.created_at)) {
    throw new TypeError("operator decision history predates latest event");
  }
  return value as OperatorDecisionHistory;
}

export function deriveOperatorDecisionCurrentState(
  history: OperatorDecisionHistory,
  derivedAt: string,
): OperatorDecisionCurrentState {
  const timestampValue = timestamp(derivedAt, "current state derivation time");
  const current = history.events.at(-1) ?? null;
  return {
    contract_version: "operator_decision_current_state.v1",
    operator_id: history.operator_id,
    security_id: history.security_id,
    thesis_contract_id: history.thesis_contract_id,
    current_operator_decision_id: current?.operator_decision_id ?? null,
    current_operator_action: current?.operator_action ?? null,
    current_relationship: current?.relationship ?? null,
    supersession_depth: current ? history.events.length - 1 : 0,
    derived_at: timestampValue,
  };
}

export function parseOperatorWorkflowCommand(
  value: unknown,
  context: OperatorWorkflowCommandValidationContext,
): OperatorWorkflowCommand {
  const command = record(value, "operator workflow command");
  exactKeys(command, COMMAND_KEYS, "operator workflow command");
  if (command.contract_version !== "operator_workflow_command.v1") {
    throw new TypeError("invalid operator workflow command contract version");
  }
  uuid(command.workflow_command_id, "workflow command id");
  const decision = context.decision;
  if (
    command.operator_decision_id !== decision.operator_decision_id ||
    command.operator_id !== decision.operator_id ||
    command.security_id !== decision.security_id ||
    command.thesis_contract_id !== decision.thesis_contract_id ||
    command.thesis_version_id !== decision.thesis_version_id ||
    command.committee_result_id !== decision.committee_result_id ||
    command.readiness_gate_result_id !== decision.readiness_gate_result_id
  ) {
    throw new TypeError("workflow command does not match operator decision");
  }
  if (decision.operator_action !== "request_deep_research") {
    throw new TypeError("workflow command requires deep-research decision");
  }
  if (command.command_type !== "create_research_request") {
    throw new TypeError("invalid workflow command type");
  }
  if (
    command.command_policy_version !== "operator_workflow_command_policy.v1"
  ) {
    throw new TypeError("invalid workflow command policy version");
  }
  nonEmptyString(command.idempotency_key, "workflow command idempotency key");
  if (command.command_state !== "pending") {
    throw new TypeError("invalid workflow command state");
  }
  const createdAt = timestamp(command.created_at, "workflow command creation time");
  if (Date.parse(createdAt) < Date.parse(decision.created_at)) {
    throw new TypeError("workflow command predates operator decision");
  }
  return value as OperatorWorkflowCommand;
}

export function parsePortfolioReviewHandoffMarker(
  value: unknown,
  context: PortfolioReviewHandoffValidationContext,
): PortfolioReviewHandoffMarker {
  const marker = record(value, "portfolio review handoff marker");
  exactKeys(marker, HANDOFF_KEYS, "portfolio review handoff marker");
  if (marker.contract_version !== "portfolio_review_handoff_marker.v1") {
    throw new TypeError("invalid portfolio review handoff contract version");
  }
  uuid(
    marker.portfolio_review_handoff_marker_id,
    "portfolio review handoff marker id",
  );
  const { decision, thesisVersion: thesis, readinessResult: readiness } = context;
  if (
    marker.operator_decision_id !== decision.operator_decision_id ||
    marker.operator_id !== decision.operator_id ||
    marker.operator_id !== thesis.operator_id ||
    marker.operator_id !== readiness.operator_id ||
    marker.security_id !== decision.security_id ||
    marker.security_id !== thesis.security_id ||
    marker.security_id !== readiness.security_id ||
    marker.thesis_contract_id !== decision.thesis_contract_id ||
    marker.thesis_contract_id !== thesis.thesis_contract_id ||
    marker.thesis_contract_id !== readiness.thesis_contract_id ||
    marker.thesis_version_id !== decision.thesis_version_id ||
    marker.thesis_version_id !== thesis.thesis_version_id ||
    marker.committee_result_id !== decision.committee_result_id ||
    marker.committee_result_id !== thesis.committee_result_id ||
    marker.committee_result_id !== readiness.committee_result_id ||
    marker.readiness_gate_result_id !== decision.readiness_gate_result_id ||
    marker.readiness_gate_result_id !== thesis.readiness_gate_result_id ||
    marker.readiness_gate_result_id !== readiness.readiness_gate_result_id
  ) {
    throw new TypeError("portfolio handoff does not match upstream research");
  }
  if (
    decision.operator_action !== "mark_for_future_portfolio_review" ||
    decision.relationship !== "accept"
  ) {
    throw new TypeError("portfolio handoff requires accepted handoff decision");
  }
  if (
    thesis.thesis_status !== "canonical" ||
    marker.thesis_status !== "canonical"
  ) {
    throw new TypeError("portfolio handoff requires canonical thesis");
  }
  if (
    decision.system_disposition !== "decision_ready" ||
    thesis.final_disposition !== "decision_ready" ||
    readiness.final_disposition !== "decision_ready" ||
    marker.final_system_disposition !== "decision_ready"
  ) {
    throw new TypeError("portfolio handoff requires decision-ready disposition");
  }
  if (
    readiness.readiness_status !== "passed" ||
    marker.readiness_status !== "passed"
  ) {
    throw new TypeError("portfolio handoff requires passed readiness gate");
  }
  if (marker.handoff_policy_version !== "portfolio_review_handoff_policy.v1") {
    throw new TypeError("invalid portfolio handoff policy version");
  }
  nonEmptyString(marker.idempotency_key, "portfolio handoff idempotency key");
  const createdAt = timestamp(marker.created_at, "portfolio handoff creation time");
  if (Date.parse(createdAt) < Date.parse(decision.created_at)) {
    throw new TypeError("portfolio handoff predates operator decision");
  }
  return value as PortfolioReviewHandoffMarker;
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  if (typeof value === "object" && value !== null) {
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(object[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function resolveReplay<T extends { idempotency_key: string }>(
  existing: readonly T[],
  candidate: T,
  id: (value: T) => string,
  label: string,
): IdempotentReplayResolution<T> {
  const matched = existing.find(
    (value) =>
      value.idempotency_key === candidate.idempotency_key ||
      id(value) === id(candidate),
  );
  if (!matched) {
    return { outcome: "created", value: candidate };
  }
  if (
    matched.idempotency_key !== candidate.idempotency_key ||
    id(matched) !== id(candidate) ||
    canonicalJson(matched) !== canonicalJson(candidate)
  ) {
    throw new TypeError(`${label} idempotency collision`);
  }
  return { outcome: "reused", value: matched };
}

export function resolveOperatorDecisionReplay(
  existing: readonly OperatorDecisionEvent[],
  candidate: OperatorDecisionEvent,
): IdempotentReplayResolution<OperatorDecisionEvent> {
  return resolveReplay(
    existing,
    candidate,
    (value) => value.operator_decision_id,
    "operator decision",
  );
}

export function resolveOperatorWorkflowCommandReplay(
  existing: readonly OperatorWorkflowCommand[],
  candidate: OperatorWorkflowCommand,
): IdempotentReplayResolution<OperatorWorkflowCommand> {
  return resolveReplay(
    existing,
    candidate,
    (value) => value.workflow_command_id,
    "operator workflow command",
  );
}

export function resolvePortfolioReviewHandoffReplay(
  existing: readonly PortfolioReviewHandoffMarker[],
  candidate: PortfolioReviewHandoffMarker,
): IdempotentReplayResolution<PortfolioReviewHandoffMarker> {
  return resolveReplay(
    existing,
    candidate,
    (value) => value.portfolio_review_handoff_marker_id,
    "portfolio review handoff",
  );
}
