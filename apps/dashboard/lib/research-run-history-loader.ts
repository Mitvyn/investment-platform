import {
  mapResearchRunRows,
  type ResearchRun,
} from "../../../packages/types/research-run.ts";

export type ResearchRunReadinessSummary = {
  readinessGateResultId: string;
  committeeStatus:
    | "complete"
    | "complete_with_abstentions"
    | "incomplete_required_grader_failed"
    | "insufficient_accepted_opinions";
  readinessStatus: "passed" | "blocked" | "not_requested";
  requestedDisposition:
    | "reject"
    | "monitor"
    | "deep_research"
    | "decision_ready";
  finalDisposition:
    | "reject"
    | "monitor"
    | "deep_research"
    | "decision_ready";
  gatePolicyVersion: string;
  evaluatedAt: string;
};

export type ResearchRunHistoryItem = {
  run: ResearchRun;
  readiness: ResearchRunReadinessSummary | null;
};

export type ResearchRunHistory = {
  latest: ResearchRunHistoryItem | null;
  items: ResearchRunHistoryItem[];
};

export type ResearchRunReadinessViewRow = {
  operator_id: string;
  research_run_id: string;
  committee_result_id: string;
  committee_memo_id: string;
  canonical_readiness: unknown;
};

type FetchResearchRunRows = (
  operatorId: string,
  securityId: string,
) => Promise<unknown[]>;

type FetchReadinessRows = (
  operatorId: string,
  researchRunIds: string[],
) => Promise<ResearchRunReadinessViewRow[]>;

const READINESS_KEYS = [
  "contract_version",
  "readiness_gate_result_id",
  "operator_id",
  "security_id",
  "thesis_contract_id",
  "research_run_id",
  "evidence_bundle_id",
  "evidence_bundle_hash",
  "validated_grader_opinion_ids",
  "committee_result_id",
  "committee_memo_id",
  "committee_status",
  "requested_disposition",
  "final_disposition",
  "readiness_status",
  "gate_policy_version",
  "passed_checks",
  "failed_checks",
  "blocking_reasons",
  "required_next_evidence",
  "evaluated_at",
] as const;

const COMMITTEE_STATUSES = new Set([
  "complete",
  "complete_with_abstentions",
  "incomplete_required_grader_failed",
  "insufficient_accepted_opinions",
]);
const READINESS_STATUSES = new Set(["passed", "blocked", "not_requested"]);
const DISPOSITIONS = new Set([
  "reject",
  "monitor",
  "deep_research",
  "decision_ready",
]);
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError(`invalid ${label}`);
  }
  return value as Record<string, unknown>;
}

function assertUuid(value: unknown, label: string) {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    throw new TypeError(`invalid ${label}`);
  }
}

export function parseResearchRunReadinessSummary(
  value: unknown,
  row: ResearchRunReadinessViewRow,
  run: ResearchRun,
): ResearchRunReadinessSummary {
  const result = record(value, "Research Run readiness summary");
  const keys = Object.keys(result).sort();
  const expectedKeys = [...READINESS_KEYS].sort();
  if (
    keys.length !== expectedKeys.length ||
    keys.some((key, index) => key !== expectedKeys[index])
  ) {
    throw new TypeError("invalid Research Run readiness summary fields");
  }
  if (result.contract_version !== "readiness_gate_result.v1") {
    throw new TypeError("invalid Research Run readiness contract version");
  }
  for (const [actual, expected] of [
    [row.operator_id, run.operator_id],
    [row.research_run_id, run.id],
    [result.operator_id, run.operator_id],
    [result.security_id, run.security_id],
    [result.thesis_contract_id, run.thesis_contract_id],
    [result.research_run_id, run.id],
    [result.committee_result_id, row.committee_result_id],
    [result.committee_memo_id, row.committee_memo_id],
  ] as const) {
    if (actual !== expected) {
      throw new TypeError(
        "Research Run readiness is outside requested ownership scope",
      );
    }
  }
  for (const [valueToCheck, label] of [
    [result.readiness_gate_result_id, "readiness gate result id"],
    [result.operator_id, "readiness operator id"],
    [result.security_id, "readiness security id"],
    [result.research_run_id, "readiness Research Run id"],
    [result.committee_result_id, "readiness committee id"],
    [result.committee_memo_id, "readiness memo id"],
  ] as const) {
    assertUuid(valueToCheck, label);
  }
  if (
    !COMMITTEE_STATUSES.has(String(result.committee_status)) ||
    !READINESS_STATUSES.has(String(result.readiness_status)) ||
    !DISPOSITIONS.has(String(result.requested_disposition)) ||
    !DISPOSITIONS.has(String(result.final_disposition)) ||
    typeof result.gate_policy_version !== "string" ||
    result.gate_policy_version.length === 0 ||
    typeof result.evaluated_at !== "string" ||
    Number.isNaN(Date.parse(result.evaluated_at)) ||
    !Array.isArray(result.passed_checks) ||
    !Array.isArray(result.failed_checks) ||
    !Array.isArray(result.blocking_reasons) ||
    !Array.isArray(result.required_next_evidence)
  ) {
    throw new TypeError("invalid Research Run readiness state");
  }
  const requested = String(result.requested_disposition);
  const finalDisposition = String(result.final_disposition);
  const readinessStatus = String(result.readiness_status);
  const allowedPair =
    requested === finalDisposition ||
    (requested === "decision_ready" &&
      finalDisposition === "deep_research");
  if (!allowedPair) {
    throw new TypeError("Research Run readiness cannot upgrade disposition");
  }
  if (
    (requested !== "decision_ready" &&
      (readinessStatus !== "not_requested" ||
        finalDisposition !== requested)) ||
    (finalDisposition === "decision_ready" &&
      (readinessStatus !== "passed" ||
        result.failed_checks.length !== 0 ||
        result.blocking_reasons.length !== 0 ||
        result.required_next_evidence.length !== 0)) ||
    (requested === "decision_ready" &&
      finalDisposition === "deep_research" &&
      (readinessStatus !== "blocked" ||
        result.failed_checks.length === 0 ||
        result.blocking_reasons.length === 0 ||
        result.required_next_evidence.length === 0))
  ) {
    throw new TypeError("invalid Research Run readiness outcome");
  }
  return {
    readinessGateResultId: String(result.readiness_gate_result_id),
    committeeStatus: result.committee_status as ResearchRunReadinessSummary["committeeStatus"],
    readinessStatus: result.readiness_status as ResearchRunReadinessSummary["readinessStatus"],
    requestedDisposition: result.requested_disposition as ResearchRunReadinessSummary["requestedDisposition"],
    finalDisposition: result.final_disposition as ResearchRunReadinessSummary["finalDisposition"],
    gatePolicyVersion: result.gate_policy_version,
    evaluatedAt: result.evaluated_at,
  };
}

function groupRowsByRun(rows: unknown[]): unknown[][] {
  const groups = new Map<string, unknown[]>();
  for (const value of rows) {
    if (
      typeof value !== "object" ||
      value === null ||
      Array.isArray(value) ||
      typeof (value as Record<string, unknown>).research_run_id !== "string"
    ) {
      throw new TypeError("invalid Research Run history row");
    }
    const runId = (value as Record<string, string>).research_run_id;
    groups.set(runId, [...(groups.get(runId) ?? []), value]);
  }
  return [...groups.values()];
}

export function createResearchRunHistoryLoader(
  fetchResearchRunRows: FetchResearchRunRows,
  fetchReadinessRows: FetchReadinessRows,
) {
  return async function loadResearchRunHistory(
    operatorId: string,
    securityId: string,
  ): Promise<ResearchRunHistory> {
    const rows = await fetchResearchRunRows(operatorId, securityId);
    const runs = groupRowsByRun(rows).map(mapResearchRunRows);
    if (
      runs.some(
        (run) =>
          run.operator_id !== operatorId || run.security_id !== securityId,
      )
    ) {
      throw new TypeError(
        "Research Run history is outside requested ownership scope",
      );
    }
    runs.sort(
      (left, right) =>
        Date.parse(right.created_at) - Date.parse(left.created_at) ||
        right.id.localeCompare(left.id),
    );
    if (runs.length === 0) {
      return { latest: null, items: [] };
    }
    const readinessRows = await fetchReadinessRows(
      operatorId,
      runs.map((run) => run.id),
    );
    const runIds = new Set(runs.map((run) => run.id));
    const readinessByRun = new Map<string, ResearchRunReadinessViewRow>();
    for (const row of readinessRows) {
      if (
        row.operator_id !== operatorId ||
        !runIds.has(row.research_run_id)
      ) {
        throw new TypeError(
          "Readiness data is outside requested Research Run history",
        );
      }
      if (readinessByRun.has(row.research_run_id)) {
        throw new TypeError(
          "Research Run must have at most one readiness outcome",
        );
      }
      readinessByRun.set(row.research_run_id, row);
    }
    const items = runs.map((run) => {
      const row = readinessByRun.get(run.id);
      return {
        run,
        readiness:
          row === undefined
            ? null
            : parseResearchRunReadinessSummary(
                row.canonical_readiness,
                row,
                run,
              ),
      };
    });
    return { latest: items[0] ?? null, items };
  };
}
