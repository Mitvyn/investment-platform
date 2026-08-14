export type ResearchRunCommandState =
  | "queued"
  | "running"
  | "blocked"
  | "failed"
  | "completed";

type ResearchRunCommandReceiptBase = {
  command_id: string;
  operator_id: string;
  security_id: string;
  question_type_version:
    | "biotech_moonshot_catalyst_assessment.v1"
    | "biotech_moonshot_catalyst_personal_research_assessment.v1";
  workflow_config_version:
    | "biotech-moonshot-catalyst-v1"
    | "biotech-moonshot-catalyst-personal-research-v1";
  as_of_cutoff: string;
  operator_focus_normalized: string | null;
  idempotency_key: string;
  state: ResearchRunCommandState;
  blocking_reason_codes: string[];
  error_code: string | null;
  research_run_id: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type HistoricalResearchRunCommandReceipt =
  ResearchRunCommandReceiptBase & {
    contract_version: "research_run_command_receipt.v1";
  };

export type PreparedResearchCaptureIdentity = {
  capture_id: string;
  capture_revision: number;
  capture_content_hash: string;
};

const PREPARED_CAPTURE_KEYS = [
  "capture_id",
  "capture_revision",
  "capture_content_hash",
] as const;

export type CurrentResearchRunCommandReceipt =
  ResearchRunCommandReceiptBase &
    PreparedResearchCaptureIdentity & {
      contract_version: "research_run_command_receipt.v2";
    };

export type ResearchRunCommandReceipt =
  | HistoricalResearchRunCommandReceipt
  | CurrentResearchRunCommandReceipt;

const RECEIPT_V1_KEYS = [
  "contract_version",
  "command_id",
  "operator_id",
  "security_id",
  "question_type_version",
  "workflow_config_version",
  "as_of_cutoff",
  "operator_focus_normalized",
  "idempotency_key",
  "state",
  "blocking_reason_codes",
  "error_code",
  "research_run_id",
  "created_at",
  "updated_at",
  "started_at",
  "finished_at",
] as const;

const RECEIPT_V2_KEYS = [
  ...RECEIPT_V1_KEYS,
  "capture_id",
  "capture_revision",
  "capture_content_hash",
] as const;

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const REASON_CODE_PATTERN = /^[a-z][a-z0-9_]{0,127}$/;
const BLOCKED_REASON_CODES = [
  "generic_primary_source_pipeline_unavailable",
  "persistent_committee_worker_unavailable",
  "model_execution_inactive",
  "licensed_valuation_unavailable",
  "hosted_isolation_unverified",
] as const;
const PERSONAL_RESEARCH_BLOCKED_REASON_CODES = [
  "generic_primary_source_pipeline_unavailable",
  "persistent_committee_worker_unavailable",
  "model_execution_inactive",
  "personal_research_valuation_pipeline_unavailable",
  "hosted_isolation_unverified",
] as const;
const COMMAND_CONTRACTS = [
  [
    "biotech_moonshot_catalyst_assessment.v1",
    "biotech-moonshot-catalyst-v1",
  ],
  [
    "biotech_moonshot_catalyst_personal_research_assessment.v1",
    "biotech-moonshot-catalyst-personal-research-v1",
  ],
] as const;

function isTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /(?:z|[+-]\d{2}:\d{2})$/i.test(value) &&
    !Number.isNaN(Date.parse(value))
  );
}

export function parsePreparedResearchCaptureIdentity(
  value: unknown,
): PreparedResearchCaptureIdentity {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("invalid prepared Research capture identity");
  }
  const identity = value as Record<string, unknown>;
  const actualKeys = Object.keys(identity).sort();
  const expectedKeys = [...PREPARED_CAPTURE_KEYS].sort();
  if (
    actualKeys.length !== expectedKeys.length ||
    actualKeys.some((key, index) => key !== expectedKeys[index]) ||
    typeof identity.capture_id !== "string" ||
    !UUID_PATTERN.test(identity.capture_id) ||
    !Number.isInteger(identity.capture_revision) ||
    (identity.capture_revision as number) < 1 ||
    (identity.capture_revision as number) > 2_147_483_647 ||
    typeof identity.capture_content_hash !== "string" ||
    !/^[0-9a-f]{64}$/.test(identity.capture_content_hash)
  ) {
    throw new TypeError("invalid prepared Research capture identity");
  }
  return identity as PreparedResearchCaptureIdentity;
}

export function parseResearchRunCommandReceipt(
  value: unknown,
): ResearchRunCommandReceipt {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    throw new TypeError("invalid Research Run command receipt");
  }
  const receipt = value as Record<string, unknown>;
  const receiptVersion = receipt.contract_version;
  if (
    receiptVersion !== "research_run_command_receipt.v1" &&
    receiptVersion !== "research_run_command_receipt.v2"
  ) {
    throw new TypeError("invalid Research Run command receipt");
  }
  const actualKeys = Object.keys(receipt).sort();
  const expectedKeys = [
    ...(receiptVersion === "research_run_command_receipt.v2"
      ? RECEIPT_V2_KEYS
      : RECEIPT_V1_KEYS),
  ].sort();
  if (
    actualKeys.length !== expectedKeys.length ||
    actualKeys.some((key, index) => key !== expectedKeys[index])
  ) {
    throw new TypeError("invalid Research Run command receipt fields");
  }
  for (const field of ["command_id", "operator_id", "security_id"] as const) {
    if (
      typeof receipt[field] !== "string" ||
      !UUID_PATTERN.test(receipt[field])
    ) {
      throw new TypeError(`invalid Research Run command ${field}`);
    }
  }
  if (receiptVersion === "research_run_command_receipt.v2") {
    try {
      parsePreparedResearchCaptureIdentity({
        capture_id: receipt.capture_id,
        capture_revision: receipt.capture_revision,
        capture_content_hash: receipt.capture_content_hash,
      });
    } catch {
      throw new TypeError("invalid Research Run command capture identity");
    }
  }
  const contractIdentityValid = COMMAND_CONTRACTS.some(
    ([questionTypeVersion, workflowConfigVersion]) =>
      receipt.question_type_version === questionTypeVersion &&
      receipt.workflow_config_version === workflowConfigVersion,
  );
  if (
    !contractIdentityValid ||
    !isTimestamp(receipt.as_of_cutoff) ||
    !isTimestamp(receipt.created_at) ||
    !isTimestamp(receipt.updated_at) ||
    typeof receipt.idempotency_key !== "string" ||
    !/^[0-9a-f]{64}$/.test(receipt.idempotency_key)
  ) {
    throw new TypeError("invalid Research Run command contract identity");
  }
  if (
    receipt.operator_focus_normalized !== null &&
    (typeof receipt.operator_focus_normalized !== "string" ||
      receipt.operator_focus_normalized.length === 0 ||
      receipt.operator_focus_normalized.length > 2_000 ||
      receipt.operator_focus_normalized.replace(/\s+/g, " ").trim() !==
        receipt.operator_focus_normalized)
  ) {
    throw new TypeError("invalid Research Run command focus");
  }
  if (
    !["queued", "running", "blocked", "failed", "completed"].includes(
      String(receipt.state),
    ) ||
    !Array.isArray(receipt.blocking_reason_codes) ||
    !receipt.blocking_reason_codes.every(
      (reason) =>
        typeof reason === "string" && REASON_CODE_PATTERN.test(reason),
    ) ||
    new Set(receipt.blocking_reason_codes).size !==
      receipt.blocking_reason_codes.length ||
    (receipt.error_code !== null &&
      (typeof receipt.error_code !== "string" ||
        !REASON_CODE_PATTERN.test(receipt.error_code))) ||
    (receipt.research_run_id !== null &&
      (typeof receipt.research_run_id !== "string" ||
        !UUID_PATTERN.test(receipt.research_run_id))) ||
    (receipt.started_at !== null && !isTimestamp(receipt.started_at)) ||
    (receipt.finished_at !== null && !isTimestamp(receipt.finished_at))
  ) {
    throw new TypeError("invalid Research Run command state");
  }
  const blocked = receipt.state === "blocked";
  const failed = receipt.state === "failed";
  const completed = receipt.state === "completed";
  const queued = receipt.state === "queued";
  const running = receipt.state === "running";
  const expectedBlockedReasonCodes =
    receipt.question_type_version ===
    "biotech_moonshot_catalyst_personal_research_assessment.v1"
      ? PERSONAL_RESEARCH_BLOCKED_REASON_CODES
      : BLOCKED_REASON_CODES;
  const createdAt = Date.parse(receipt.created_at as string);
  const updatedAt = Date.parse(receipt.updated_at as string);
  const startedAt =
    receipt.started_at === null
      ? null
      : Date.parse(receipt.started_at as string);
  const finishedAt =
    receipt.finished_at === null
      ? null
      : Date.parse(receipt.finished_at as string);
  if (
    (blocked &&
      (receipt.blocking_reason_codes.length !==
        expectedBlockedReasonCodes.length ||
        receipt.blocking_reason_codes.some(
          (reason, index) => reason !== expectedBlockedReasonCodes[index],
        ) ||
        receipt.error_code !== null ||
        receipt.research_run_id !== null ||
        receipt.started_at !== null ||
        receipt.finished_at === null)) ||
    (failed &&
      (receipt.error_code === null ||
        receipt.blocking_reason_codes.length !== 0 ||
        receipt.started_at === null ||
        receipt.finished_at === null)) ||
    (completed &&
      (receipt.research_run_id === null ||
        receipt.blocking_reason_codes.length !== 0 ||
        receipt.error_code !== null ||
        receipt.started_at === null ||
        receipt.finished_at === null)) ||
    (queued &&
      (receipt.blocking_reason_codes.length !== 0 ||
        receipt.error_code !== null ||
        receipt.research_run_id !== null ||
        receipt.started_at !== null ||
        receipt.finished_at !== null)) ||
    (running &&
      (receipt.blocking_reason_codes.length !== 0 ||
        receipt.error_code !== null ||
        receipt.research_run_id !== null ||
        receipt.started_at === null ||
        receipt.finished_at !== null)) ||
    updatedAt < createdAt ||
    (startedAt !== null && startedAt < createdAt) ||
    (finishedAt !== null && finishedAt < (startedAt ?? createdAt))
  ) {
    throw new TypeError("contradictory Research Run command state");
  }
  return receipt as ResearchRunCommandReceipt;
}
