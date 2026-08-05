export const RESEARCH_COMMAND_STAGES = [
  "research_run",
  "evidence_bundle",
  "valuation_snapshot",
  "grader_committee",
  "committee_memo",
  "readiness_thesis",
] as const;

export type ResearchRunCommandStage =
  (typeof RESEARCH_COMMAND_STAGES)[number];

export type ResearchRunCommandProgress = {
  contract_version: "research_run_command_progress.v1";
  operator_id: string;
  command_id: string;
  command_state: "blocked" | "queued" | "running" | "completed" | "failed";
  attempt_id: string | null;
  attempt_number: 1 | 2 | null;
  attempt_state: "running" | "completed" | "failed" | null;
  active_stage: ResearchRunCommandStage | null;
  completed_stages: ResearchRunCommandStage[];
  lease_started_at: string | null;
  lease_expires_at: string | null;
  failure_stage: ResearchRunCommandStage | null;
  error_code: string | null;
  retryable: boolean | null;
  updated_at: string;
};

export type ResearchRunCommandProgressViewRow = {
  operator_id: unknown;
  command_id: unknown;
  canonical_progress: unknown;
};

type FetchResearchRunCommandProgressRows = (
  operatorId: string,
  commandId: string,
) => Promise<ResearchRunCommandProgressViewRow[]>;

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PROGRESS_FIELDS = [
  "contract_version",
  "operator_id",
  "command_id",
  "command_state",
  "attempt_id",
  "attempt_number",
  "attempt_state",
  "active_stage",
  "completed_stages",
  "lease_started_at",
  "lease_expires_at",
  "failure_stage",
  "error_code",
  "retryable",
  "updated_at",
] as const;

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError("invalid Research Run command progress");
  }
  return value as Record<string, unknown>;
}

function timestamp(value: unknown, label: string): string {
  if (typeof value !== "string" || Number.isNaN(Date.parse(value))) {
    throw new TypeError(`invalid Research Run command ${label}`);
  }
  return value;
}

function parseProgress(
  value: unknown,
  operatorId: string,
  commandId: string,
): ResearchRunCommandProgress {
  const progress = object(value);
  const keys = Object.keys(progress).sort();
  const expected = [...PROGRESS_FIELDS].sort();
  if (
    keys.length !== expected.length ||
    keys.some((key, index) => key !== expected[index])
  ) {
    throw new TypeError("invalid Research Run command progress fields");
  }
  if (
    progress.contract_version !== "research_run_command_progress.v1" ||
    progress.operator_id !== operatorId ||
    progress.command_id !== commandId
  ) {
    throw new TypeError(
      "Research Run command progress is outside requested owner scope",
    );
  }
  if (
    !UUID_PATTERN.test(operatorId) ||
    !UUID_PATTERN.test(commandId) ||
    !Array.isArray(progress.completed_stages)
  ) {
    throw new TypeError("invalid Research Run command progress identity");
  }
  if (
    (progress.command_state === "queued" ||
      progress.command_state === "blocked") &&
    progress.attempt_id === null
  ) {
    if (
      progress.attempt_number !== null ||
      progress.attempt_state !== null ||
      progress.active_stage !== null ||
      progress.completed_stages.length !== 0 ||
      progress.lease_started_at !== null ||
      progress.lease_expires_at !== null ||
      progress.failure_stage !== null ||
      progress.error_code !== null ||
      progress.retryable !== null
    ) {
      throw new TypeError(
        "invalid inactive Research Run command progress",
      );
    }
    return {
      contract_version: "research_run_command_progress.v1",
      operator_id: operatorId,
      command_id: commandId,
      command_state: progress.command_state,
      attempt_id: null,
      attempt_number: null,
      attempt_state: null,
      active_stage: null,
      completed_stages: [],
      lease_started_at: null,
      lease_expires_at: null,
      failure_stage: null,
      error_code: null,
      retryable: null,
      updated_at: timestamp(progress.updated_at, "progress timestamp"),
    };
  }
  if (
    typeof progress.attempt_id !== "string" ||
    !UUID_PATTERN.test(progress.attempt_id) ||
    (progress.attempt_number !== 1 && progress.attempt_number !== 2)
  ) {
    throw new TypeError("invalid Research Run command attempt progress");
  }
  const completed = progress.completed_stages as ResearchRunCommandStage[];
  if (
    completed.length > RESEARCH_COMMAND_STAGES.length ||
    completed.some(
      (stage, index) => stage !== RESEARCH_COMMAND_STAGES[index],
    )
  ) {
    throw new TypeError("invalid Research Run command stage progress");
  }
  const leaseStartedAt = timestamp(
    progress.lease_started_at,
    "lease start",
  );
  const leaseExpiresAt = timestamp(
    progress.lease_expires_at,
    "lease expiry",
  );
  const updatedAt = timestamp(progress.updated_at, "progress timestamp");
  if (
    Date.parse(leaseExpiresAt) <= Date.parse(leaseStartedAt) ||
    Date.parse(updatedAt) < Date.parse(leaseStartedAt)
  ) {
    throw new TypeError("invalid Research Run command lease chronology");
  }
  const nextStage = RESEARCH_COMMAND_STAGES[completed.length] ?? null;
  const running = progress.command_state === "running";
  const failed = progress.command_state === "failed";
  const completedCommand = progress.command_state === "completed";
  const queuedRetry = progress.command_state === "queued";
  if (
    (running &&
      (progress.attempt_state !== "running" ||
        progress.active_stage !== nextStage ||
        progress.failure_stage !== null ||
        progress.error_code !== null ||
        progress.retryable !== null)) ||
    (failed &&
      (progress.attempt_state !== "failed" ||
        progress.active_stage !== null ||
        progress.failure_stage !== nextStage ||
        typeof progress.error_code !== "string" ||
        !/^[a-z][a-z0-9_]{0,127}$/.test(progress.error_code) ||
        typeof progress.retryable !== "boolean")) ||
    (completedCommand &&
      (progress.attempt_state !== "completed" ||
        completed.length !== RESEARCH_COMMAND_STAGES.length ||
        progress.active_stage !== null ||
        progress.failure_stage !== null ||
        progress.error_code !== null ||
        progress.retryable !== null)) ||
    (queuedRetry &&
      (progress.attempt_state !== "failed" ||
        progress.active_stage !== null ||
        progress.failure_stage !== nextStage ||
        typeof progress.error_code !== "string" ||
        !/^[a-z][a-z0-9_]{0,127}$/.test(progress.error_code) ||
        progress.retryable !== true)) ||
    (!running && !failed && !completedCommand && !queuedRetry)
  ) {
    throw new TypeError("invalid Research Run command terminal progress");
  }
  return {
    contract_version: "research_run_command_progress.v1",
    operator_id: operatorId,
    command_id: commandId,
    command_state: progress.command_state as
      | "running"
      | "completed"
      | "failed"
      | "queued",
    attempt_id: progress.attempt_id,
    attempt_number: progress.attempt_number,
    attempt_state: progress.attempt_state as "running" | "completed" | "failed",
    active_stage: progress.active_stage as ResearchRunCommandStage | null,
    completed_stages: [...completed],
    lease_started_at: leaseStartedAt,
    lease_expires_at: leaseExpiresAt,
    failure_stage: progress.failure_stage as ResearchRunCommandStage | null,
    error_code: progress.error_code as string | null,
    retryable: progress.retryable as boolean | null,
    updated_at: updatedAt,
  };
}

export function createResearchRunCommandProgressLoader(
  fetchRows: FetchResearchRunCommandProgressRows,
) {
  return async function loadResearchRunCommandProgress(
    operatorId: string,
    commandId: string,
  ): Promise<ResearchRunCommandProgress | null> {
    const rows = await fetchRows(operatorId, commandId);
    if (rows.length === 0) return null;
    if (rows.length !== 1) {
      throw new TypeError("Research Run command progress is ambiguous");
    }
    const row = rows[0];
    if (row.operator_id !== operatorId || row.command_id !== commandId) {
      throw new TypeError(
        "Research Run command progress is outside requested owner scope",
      );
    }
    return parseProgress(row.canonical_progress, operatorId, commandId);
  };
}
