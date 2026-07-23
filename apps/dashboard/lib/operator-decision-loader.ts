import {
  deriveOperatorDecisionCurrentState,
  parseOperatorDecisionEvent,
  parseOperatorDecisionHistory,
  parseOperatorWorkflowCommand,
  parsePortfolioReviewHandoffMarker,
  type OperatorDecisionCurrentState,
  type OperatorDecisionEvent,
  type OperatorDecisionHistory,
  type OperatorWorkflowCommand,
  type PortfolioReviewHandoffMarker,
} from "../../../packages/types/operator-decision.ts";
import type {
  ReadinessGateResult,
  ThesisVersion,
} from "../../../packages/types/readiness-thesis.ts";

export type OperatorDecisionHistoryViewRow = {
  operator_id: string;
  security_id: string;
  thesis_contract_id: string;
  canonical_history: unknown;
};

export type CurrentOperatorDecisionViewRow = {
  operator_id: string;
  security_id: string;
  thesis_contract_id: string;
  current_operator_decision_id: string;
  canonical_current_state: unknown;
};

export type OperatorDecisionEffectViewRow = {
  operator_id: string;
  security_id: string;
  thesis_contract_id: string;
  operator_decision_id: string;
  thesis_version_id: string;
  committee_result_id: string;
  readiness_gate_result_id: string;
  canonical_decision: unknown;
  canonical_thesis: unknown;
  canonical_readiness: unknown;
  canonical_command: unknown | null;
  canonical_marker: unknown | null;
};

type FetchHistoryRows = (
  operatorId: string,
  securityId: string,
  thesisContractId: string,
) => Promise<OperatorDecisionHistoryViewRow[]>;

type FetchCurrentRows = (
  operatorId: string,
  securityId: string,
  thesisContractId: string,
) => Promise<CurrentOperatorDecisionViewRow[]>;

type FetchEffectRows = (
  operatorId: string,
  securityId: string,
  thesisContractId: string,
) => Promise<OperatorDecisionEffectViewRow[]>;

function onlyRow<TRow>(rows: TRow[], label: string): TRow | null {
  if (rows.length === 0) return null;
  if (rows.length !== 1) {
    throw new TypeError(`Operator decision chain must have at most one ${label}`);
  }
  return rows[0];
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError(`invalid ${label}`);
  }
  return value as Record<string, unknown>;
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function assertScope(
  row: {
    operator_id: string;
    security_id: string;
    thesis_contract_id: string;
  },
  operatorId: string,
  securityId: string,
  thesisContractId: string,
) {
  if (
    row.operator_id !== operatorId ||
    row.security_id !== securityId ||
    row.thesis_contract_id !== thesisContractId
  ) {
    throw new TypeError("Operator decision row is outside requested ownership scope");
  }
}

export function createOperatorDecisionLoader(
  fetchHistoryRows: FetchHistoryRows,
  fetchCurrentRows: FetchCurrentRows,
  fetchEffectRows: FetchEffectRows,
) {
  return async function loadOperatorDecisionChain(
    operatorId: string,
    securityId: string,
    thesisContractId: string,
  ) {
    const [historyRows, currentRows, effectRows] = await Promise.all([
      fetchHistoryRows(operatorId, securityId, thesisContractId),
      fetchCurrentRows(operatorId, securityId, thesisContractId),
      fetchEffectRows(operatorId, securityId, thesisContractId),
    ]);
    const historyRow = onlyRow(historyRows, "history row");
    const currentRow = onlyRow(currentRows, "current-state row");

    if (historyRow === null) {
      if (currentRow !== null || effectRows.length > 0) {
        throw new TypeError("Operator decision effects exist without history");
      }
      return {
        history: null,
        current: null,
        commands: [] as OperatorWorkflowCommand[],
        handoffMarkers: [] as PortfolioReviewHandoffMarker[],
      };
    }
    if (currentRow === null) {
      throw new TypeError("Operator decision history is missing current state");
    }
    assertScope(historyRow, operatorId, securityId, thesisContractId);
    assertScope(currentRow, operatorId, securityId, thesisContractId);

    const contexts: Array<{
      thesisVersion: ThesisVersion;
      readinessResult: ReadinessGateResult;
    }> = [];
    const decisions = new Map<string, OperatorDecisionEvent>();
    const commands: OperatorWorkflowCommand[] = [];
    const handoffMarkers: PortfolioReviewHandoffMarker[] = [];

    for (const row of effectRows) {
      assertScope(row, operatorId, securityId, thesisContractId);
      const thesis = object(row.canonical_thesis, "canonical thesis") as ThesisVersion;
      const readiness = object(
        row.canonical_readiness,
        "canonical readiness",
      ) as ReadinessGateResult;
      const context = { thesisVersion: thesis, readinessResult: readiness };
      const decision = parseOperatorDecisionEvent(row.canonical_decision, context);
      if (
        row.operator_decision_id !== decision.operator_decision_id ||
        row.thesis_version_id !== decision.thesis_version_id ||
        row.committee_result_id !== decision.committee_result_id ||
        row.readiness_gate_result_id !== decision.readiness_gate_result_id ||
        decisions.has(decision.operator_decision_id)
      ) {
        throw new TypeError("Operator decision effect identity mismatch");
      }
      contexts.push(context);
      decisions.set(decision.operator_decision_id, decision);
      if (row.canonical_command !== null) {
        commands.push(
          parseOperatorWorkflowCommand(row.canonical_command, { decision }),
        );
      }
      if (row.canonical_marker !== null) {
        handoffMarkers.push(
          parsePortfolioReviewHandoffMarker(row.canonical_marker, {
            decision,
            thesisVersion: thesis,
            readinessResult: readiness,
          }),
        );
      }
    }

    const history = parseOperatorDecisionHistory(
      historyRow.canonical_history,
      contexts,
    );
    if (
      history.operator_id !== operatorId ||
      history.security_id !== securityId ||
      history.thesis_contract_id !== thesisContractId ||
      history.events.length !== decisions.size ||
      history.events.some(
        (event) =>
          canonicalJson(event) !==
          canonicalJson(decisions.get(event.operator_decision_id)),
      )
    ) {
      throw new TypeError("Operator decision history does not match effects");
    }

    const rawCurrent = object(
      currentRow.canonical_current_state,
      "canonical current operator decision",
    );
    if (typeof rawCurrent.derived_at !== "string") {
      throw new TypeError("invalid current operator decision derivation time");
    }
    const current = deriveOperatorDecisionCurrentState(
      history,
      rawCurrent.derived_at,
    );
    if (
      currentRow.current_operator_decision_id !==
        current.current_operator_decision_id ||
      canonicalJson(current) !== canonicalJson(rawCurrent)
    ) {
      throw new TypeError("Current operator decision does not match history");
    }

    return { history, current, commands, handoffMarkers };
  };
}

export type OperatorDecisionLoadResult = {
  history: OperatorDecisionHistory | null;
  current: OperatorDecisionCurrentState | null;
  commands: OperatorWorkflowCommand[];
  handoffMarkers: PortfolioReviewHandoffMarker[];
};
