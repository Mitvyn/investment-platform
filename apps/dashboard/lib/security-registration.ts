const TICKER_PATTERN = /^[A-Z][A-Z0-9.-]{0,9}$/;
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type Claims = Record<string, unknown>;

type RegistrationRpcClient = {
  rpc(
    name: string,
    args: Record<string, string>,
  ): PromiseLike<{ data: unknown; error: { message: string } | null }>;
};

export type SecurityRegistrationRequest = {
  contract_version: "security_registration_request.v1";
  ticker: string;
};

export type WorkflowJobReceipt = {
  contract_version: "workflow_job_receipt.v1";
  job_id: string;
  operator_id: string;
  job_type: "security_onboarding";
  state: "queued" | "running" | "completed" | "failed";
  idempotency_key: string;
  ticker: string;
  security_id: string | null;
  blocking_reasons: string[];
  error_code: string | null;
  created_at: string;
  updated_at: string;
};

function requiredText(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`invalid workflow job ${label}`);
  }
}

export function parseWorkflowJobReceipt(value: unknown): WorkflowJobReceipt {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("invalid workflow job receipt");
  }
  const row = value as Record<string, unknown>;
  if (row.contract_version !== "workflow_job_receipt.v1") {
    throw new Error("invalid workflow job receipt contract");
  }
  for (const key of [
    "job_id",
    "operator_id",
    "idempotency_key",
    "ticker",
    "created_at",
    "updated_at",
  ]) {
    requiredText(row[key], key);
  }
  if (
    !UUID_PATTERN.test(row.job_id as string) ||
    !UUID_PATTERN.test(row.operator_id as string)
  ) {
    throw new Error("invalid workflow job identity");
  }
  if (row.job_type !== "security_onboarding") {
    throw new Error("invalid workflow job type");
  }
  if (!["queued", "running", "completed", "failed"].includes(String(row.state))) {
    throw new Error("invalid workflow job state");
  }
  if (!TICKER_PATTERN.test(row.ticker as string)) {
    throw new Error("invalid workflow job ticker");
  }
  if (
    row.security_id !== null &&
    (typeof row.security_id !== "string" ||
      !UUID_PATTERN.test(row.security_id))
  ) {
    throw new Error("invalid workflow job security identity");
  }
  if (
    !Array.isArray(row.blocking_reasons) ||
    !row.blocking_reasons.every(
      (reason) => typeof reason === "string" && reason.length > 0,
    )
  ) {
    throw new Error("invalid workflow job blocking reasons");
  }
  if (row.error_code !== null && typeof row.error_code !== "string") {
    throw new Error("invalid workflow job error code");
  }
  return row as WorkflowJobReceipt;
}

export async function enqueueSecurityRegistration(
  client: RegistrationRpcClient,
  claims: Claims,
  request: SecurityRegistrationRequest,
): Promise<WorkflowJobReceipt> {
  const operatorId = claims.sub;
  if (typeof operatorId !== "string" || !UUID_PATTERN.test(operatorId)) {
    throw new Error("authenticated operator required");
  }
  if (request.contract_version !== "security_registration_request.v1") {
    throw new Error("unsupported security registration contract");
  }
  const ticker = request.ticker.trim().toUpperCase();
  if (!TICKER_PATTERN.test(ticker)) {
    throw new Error("ticker has invalid format");
  }

  const { data, error } = await client.rpc(
    "iros_enqueue_security_registration",
    { p_ticker: ticker },
  );
  if (error) {
    throw new Error(`security registration enqueue failed: ${error.message}`);
  }
  if (!Array.isArray(data) || data.length !== 1) {
    throw new Error("security registration enqueue returned invalid receipt count");
  }
  const receipt = parseWorkflowJobReceipt(data[0]);
  if (receipt.operator_id !== operatorId) {
    throw new Error("workflow job owner mismatch");
  }
  if (receipt.ticker !== ticker) {
    throw new Error("workflow job ticker mismatch");
  }
  return receipt;
}
