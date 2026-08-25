import {
  parsePreparedResearchCaptureIdentity,
  type PreparedResearchCaptureIdentity,
} from "../../../packages/types/research-run-command.ts";
import {
  RESEARCH_CONTRACTS,
  normalizeResearchQuestionRequest,
  parseResearchQuestionRequest,
  type ResearchQuestionRequest,
} from "../../../packages/types/research-run.ts";
import {
  RESEARCH_COMMAND_STAGES,
  type ResearchRunCommandProgress,
  type ResearchRunCommandStage,
} from "./research-run-command-progress-loader.ts";

type DesktopEnvironment = Record<string, string | undefined>;
type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CODE_PATTERN = /^[a-z][a-z0-9_]{0,127}$/;
const LOCAL_RECEIPT_FIELDS = [
  "as_of_cutoff",
  "blocking_reason_codes",
  "capture_content_hash",
  "capture_id",
  "capture_revision",
  "command_id",
  "command_state",
  "contract_version",
  "created_at",
  "error_code",
  "finished_at",
  "idempotency_key",
  "operator_focus_normalized",
  "operator_id",
  "question_type_version",
  "research_run_id",
  "security_id",
  "started_at",
  "updated_at",
  "workflow_config_version",
] as const;
const LOCAL_PROGRESS_FIELDS = [
  "active_stage",
  "attempt_id",
  "attempt_number",
  "attempt_state",
  "command_id",
  "command_state",
  "completed_stages",
  "contract_version",
  "error_code",
  "failure_stage",
  "lease_expires_at",
  "lease_started_at",
  "operator_id",
  "retryable",
  "updated_at",
] as const;

export type LocalResearchRunCommandReceipt = {
  contract_version: "research_run_local_command_receipt.v1";
  command_id: string;
  operator_id: string;
  security_id: string;
  question_type_version: string;
  workflow_config_version: string;
  as_of_cutoff: string;
  operator_focus_normalized: string | null;
  idempotency_key: string;
  state: "queued" | "running" | "blocked" | "failed" | "completed";
  blocking_reason_codes: string[];
  error_code: string | null;
  research_run_id: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  capture_id: string;
  capture_revision: number;
  capture_content_hash: string;
};

export type LocalResearchRunCommandResponse = {
  receipt: LocalResearchRunCommandReceipt;
  progress: ResearchRunCommandProgress;
};

export type LocalResearchRunCommandInput = {
  operatorId: string;
  securityId: string;
  ticker: string;
  request: ResearchQuestionRequest;
  preparedCapture: PreparedResearchCaptureIdentity;
  now: Date;
};

function controlContract(environment: DesktopEnvironment) {
  const origin = environment.IROS_DESKTOP_CONTROL_ORIGIN ?? "";
  const token = environment.IROS_DESKTOP_CONTROL_TOKEN ?? "";
  if (
    environment.IROS_DESKTOP !== "1" ||
    environment.IROS_DESKTOP_WORKER_STATE !== "ready" ||
    !/^http:\/\/127\.0\.0\.1:\d+$/.test(origin) ||
    token.length < 32
  ) {
    return null;
  }
  return { origin, token };
}

export function isLocalResearchRuntimeReady(
  environment: DesktopEnvironment = process.env,
): boolean {
  return controlContract(environment) !== null;
}

export async function enqueueLocalResearchRunCommand(
  input: LocalResearchRunCommandInput,
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<LocalResearchRunCommandResponse> {
  const contract = controlContract(environment);
  if (!contract) throw new Error("desktop worker unavailable");
  if (!UUID_PATTERN.test(input.operatorId) || !UUID_PATTERN.test(input.securityId)) {
    throw new TypeError("invalid local Research Run identity");
  }
  if (input.request.security_id !== input.securityId) {
    throw new TypeError("local Research Run security identity mismatch");
  }
  if (Number.isNaN(input.now.getTime())) {
    throw new TypeError("current time is invalid");
  }
  const request = normalizeResearchQuestionRequest(
    parseResearchQuestionRequest(input.request),
  );
  if (Date.parse(request.as_of_cutoff) > input.now.getTime()) {
    throw new TypeError("research cutoff cannot be in the future");
  }
  const capture = parsePreparedResearchCaptureIdentity(input.preparedCapture);
  const response = await fetcher(`${contract.origin}/v1/research/run/command`, {
    method: "POST",
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${contract.token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      operator_id: input.operatorId,
      security_id: input.securityId,
      ticker: input.ticker,
      question_type_version: request.question_type_version,
      workflow_config_version: request.workflow_config_version,
      as_of_cutoff: request.as_of_cutoff,
      operator_focus: request.operator_focus_normalized,
      capture_id: capture.capture_id,
      capture_revision: capture.capture_revision,
      capture_content_hash: capture.capture_content_hash,
    }),
    signal: AbortSignal.timeout(3_000),
  });
  if (!response.ok) throw new Error("local Research Run enqueue failed");
  return parseResponse(await response.json(), input.operatorId, input.securityId);
}

export async function loadLocalResearchRunCommand(
  operatorId: string,
  commandId: string,
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<LocalResearchRunCommandReceipt | null> {
  const response = await loadLocalResponse(
    operatorId,
    commandId,
    environment,
    fetcher,
  );
  return response?.receipt ?? null;
}

export async function loadLocalResearchRunCommandProgress(
  operatorId: string,
  commandId: string,
  environment: DesktopEnvironment = process.env,
  fetcher: FetchLike = fetch,
): Promise<ResearchRunCommandProgress | null> {
  const response = await loadLocalResponse(
    operatorId,
    commandId,
    environment,
    fetcher,
  );
  return response?.progress ?? null;
}

async function loadLocalResponse(
  operatorId: string,
  commandId: string,
  environment: DesktopEnvironment,
  fetcher: FetchLike,
): Promise<LocalResearchRunCommandResponse | null> {
  const contract = controlContract(environment);
  if (!contract) return null;
  if (!UUID_PATTERN.test(operatorId) || !UUID_PATTERN.test(commandId)) {
    return null;
  }
  const url = new URL("/v1/research/run/command", contract.origin);
  url.searchParams.set("operator_id", operatorId);
  url.searchParams.set("command_id", commandId);
  const response = await fetcher(url, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${contract.token}` },
    signal: AbortSignal.timeout(3_000),
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error("local Research Run status failed");
  return parseResponse(await response.json(), operatorId);
}

function parseResponse(
  value: unknown,
  operatorId: string,
  expectedSecurityId?: string,
): LocalResearchRunCommandResponse {
  const payload = object(value, "local Research Run response");
  exactKeys(payload, ["contract_version", "progress", "receipt"]);
  if (payload.contract_version !== "research_run_local_command_response.v1") {
    throw new TypeError("invalid local Research Run response contract");
  }
  const receipt = parseReceipt(payload.receipt, operatorId, expectedSecurityId);
  const progress = parseProgress(payload.progress, operatorId, receipt.command_id);
  return { receipt, progress };
}

function parseReceipt(
  value: unknown,
  operatorId: string,
  expectedSecurityId?: string,
): LocalResearchRunCommandReceipt {
  const receipt = object(value, "local Research Run receipt");
  exactKeys(receipt, LOCAL_RECEIPT_FIELDS);
  if (
    receipt.contract_version !== "research_run_local_command_receipt.v1" ||
    receipt.operator_id !== operatorId ||
    (expectedSecurityId !== undefined && receipt.security_id !== expectedSecurityId) ||
    !UUID_PATTERN.test(String(receipt.command_id)) ||
    !UUID_PATTERN.test(String(receipt.security_id)) ||
    !UUID_PATTERN.test(String(receipt.capture_id)) ||
    !Number.isInteger(receipt.capture_revision) ||
    (receipt.capture_revision as number) < 1 ||
    typeof receipt.question_type_version !== "string" ||
    typeof receipt.workflow_config_version !== "string" ||
    !isKnownResearchContract(
      receipt.question_type_version,
      receipt.workflow_config_version,
    ) ||
    typeof receipt.capture_content_hash !== "string" ||
    !/^[0-9a-f]{64}$/.test(receipt.capture_content_hash) ||
    typeof receipt.idempotency_key !== "string" ||
    !/^[0-9a-f]{64}$/.test(receipt.idempotency_key) ||
    !isTimestamp(receipt.as_of_cutoff) ||
    !isTimestamp(receipt.created_at) ||
    !isTimestamp(receipt.updated_at) ||
    !["queued", "running", "blocked", "failed", "completed"].includes(
      String(receipt.command_state),
    ) ||
    !Array.isArray(receipt.blocking_reason_codes) ||
    !receipt.blocking_reason_codes.every(
      (reason) => typeof reason === "string" && CODE_PATTERN.test(reason),
    ) ||
    (receipt.error_code !== null &&
      (typeof receipt.error_code !== "string" || !CODE_PATTERN.test(receipt.error_code))) ||
    (receipt.research_run_id !== null &&
      (typeof receipt.research_run_id !== "string" || !UUID_PATTERN.test(receipt.research_run_id))) ||
    (receipt.operator_focus_normalized !== null &&
      typeof receipt.operator_focus_normalized !== "string") ||
    (receipt.started_at !== null && !isTimestamp(receipt.started_at)) ||
    (receipt.finished_at !== null && !isTimestamp(receipt.finished_at))
  ) {
    throw new TypeError("invalid local Research Run receipt");
  }
  return {
    contract_version: "research_run_local_command_receipt.v1",
    command_id: receipt.command_id as string,
    operator_id: operatorId,
    security_id: receipt.security_id as string,
    question_type_version: receipt.question_type_version as string,
    workflow_config_version: receipt.workflow_config_version as string,
    as_of_cutoff: receipt.as_of_cutoff as string,
    operator_focus_normalized: receipt.operator_focus_normalized as string | null,
    idempotency_key: receipt.idempotency_key as string,
    state: receipt.command_state as LocalResearchRunCommandReceipt["state"],
    blocking_reason_codes: [...(receipt.blocking_reason_codes as string[])],
    error_code: receipt.error_code as string | null,
    research_run_id: receipt.research_run_id as string | null,
    created_at: receipt.created_at as string,
    updated_at: receipt.updated_at as string,
    started_at: receipt.started_at as string | null,
    finished_at: receipt.finished_at as string | null,
    capture_id: receipt.capture_id as string,
    capture_revision: receipt.capture_revision as number,
    capture_content_hash: receipt.capture_content_hash as string,
  };
}

function isKnownResearchContract(
  questionTypeVersion: unknown,
  workflowConfigVersion: unknown,
): boolean {
  return Object.values(RESEARCH_CONTRACTS).some(
    (contract) =>
      contract.question_type_version === questionTypeVersion &&
      contract.workflow_config_version === workflowConfigVersion,
  );
}

function parseProgress(
  value: unknown,
  operatorId: string,
  commandId: string,
): ResearchRunCommandProgress {
  const progress = object(value, "local Research Run progress");
  exactKeys(progress, LOCAL_PROGRESS_FIELDS);
  if (
    progress.contract_version !== "research_run_local_command_progress.v1" ||
    progress.operator_id !== operatorId ||
    progress.command_id !== commandId ||
    !Array.isArray(progress.completed_stages) ||
    progress.completed_stages.length > RESEARCH_COMMAND_STAGES.length ||
    progress.completed_stages.some(
      (stage, index) => stage !== RESEARCH_COMMAND_STAGES[index],
    ) ||
    (progress.attempt_id !== null && !UUID_PATTERN.test(String(progress.attempt_id))) ||
    (progress.attempt_number !== null &&
      progress.attempt_number !== 1 &&
      progress.attempt_number !== 2) ||
    (progress.active_stage !== null &&
      !RESEARCH_COMMAND_STAGES.includes(progress.active_stage as ResearchRunCommandStage)) ||
    (progress.failure_stage !== null &&
      !RESEARCH_COMMAND_STAGES.includes(progress.failure_stage as ResearchRunCommandStage)) ||
    (progress.error_code !== null &&
      (typeof progress.error_code !== "string" || !CODE_PATTERN.test(progress.error_code))) ||
    (progress.retryable !== null && typeof progress.retryable !== "boolean") ||
    !isTimestamp(progress.updated_at) ||
    (progress.lease_started_at !== null && !isTimestamp(progress.lease_started_at)) ||
    (progress.lease_expires_at !== null && !isTimestamp(progress.lease_expires_at))
  ) {
    throw new TypeError("invalid local Research Run progress");
  }
  const state = progress.command_state;
  const nextStage =
    RESEARCH_COMMAND_STAGES[progress.completed_stages.length] ?? null;
  if (
    !["queued", "running", "blocked", "failed", "completed"].includes(
      String(state),
    ) ||
    (progress.attempt_state !== null &&
      !["running", "completed", "failed"].includes(
        String(progress.attempt_state),
      )) ||
    (progress.attempt_id === null &&
      (progress.attempt_number !== null ||
        progress.attempt_state !== null ||
        progress.active_stage !== null ||
        progress.failure_stage !== null ||
        progress.error_code !== null ||
        progress.retryable !== null ||
        progress.lease_started_at !== null ||
        progress.lease_expires_at !== null)) ||
    (state === "running" &&
      (progress.attempt_state !== "running" ||
        progress.active_stage !== nextStage ||
        progress.failure_stage !== null ||
        progress.error_code !== null ||
        progress.retryable !== null)) ||
    (state === "blocked" &&
      (progress.attempt_state !== "failed" ||
        progress.active_stage !== null ||
        progress.failure_stage !== nextStage ||
        typeof progress.error_code !== "string" ||
        progress.retryable !== false)) ||
    (state === "failed" &&
      (progress.attempt_state !== "failed" ||
        progress.active_stage !== null ||
        progress.failure_stage !== nextStage ||
        typeof progress.error_code !== "string" ||
        typeof progress.retryable !== "boolean")) ||
    (state === "completed" &&
      (progress.attempt_state !== "completed" ||
        progress.completed_stages.length !== RESEARCH_COMMAND_STAGES.length ||
        progress.active_stage !== null ||
        progress.failure_stage !== null ||
        progress.error_code !== null ||
        progress.retryable !== null)) ||
    (state === "queued" &&
      progress.attempt_id !== null &&
      (progress.attempt_state !== "failed" ||
        progress.active_stage !== null ||
        progress.failure_stage !== nextStage ||
        typeof progress.error_code !== "string" ||
        progress.retryable !== true))
  ) {
    throw new TypeError("invalid local Research Run progress");
  }
  return {
    contract_version: "research_run_command_progress.v1",
    operator_id: operatorId,
    command_id: commandId,
    command_state: state as ResearchRunCommandProgress["command_state"],
    attempt_id: progress.attempt_id as string | null,
    attempt_number: progress.attempt_number as 1 | 2 | null,
    attempt_state: progress.attempt_state as ResearchRunCommandProgress["attempt_state"],
    active_stage: progress.active_stage as ResearchRunCommandStage | null,
    completed_stages: [...(progress.completed_stages as ResearchRunCommandStage[])],
    lease_started_at: progress.lease_started_at as string | null,
    lease_expires_at: progress.lease_expires_at as string | null,
    failure_stage: progress.failure_stage as ResearchRunCommandStage | null,
    error_code: progress.error_code as string | null,
    retryable: progress.retryable as boolean | null,
    updated_at: progress.updated_at as string,
  };
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError(`invalid ${label}`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, expectedKeys: readonly string[]) {
  const actual = Object.keys(value).sort();
  const expected = [...expectedKeys].sort();
  if (
    actual.length !== expected.length ||
    actual.some((key, index) => key !== expected[index])
  ) {
    throw new TypeError("invalid local Research Run response fields");
  }
}

function isTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /(?:z|[+-]\d{2}:\d{2})$/i.test(value) &&
    !Number.isNaN(Date.parse(value))
  );
}
