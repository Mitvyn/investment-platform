import {
  parseWorkflowJobReceipt,
  type WorkflowJobReceipt,
} from "./security-registration.ts";

export type SecurityJobRow = {
  id: unknown;
  operator_id: unknown;
  job_type: unknown;
  job_state: unknown;
  idempotency_key: unknown;
  ticker: unknown;
  security_id: unknown;
  error_code: unknown;
  created_at: unknown;
  updated_at: unknown;
};

type FetchSecurityJobRows = (
  operatorId: string,
  jobId: string,
) => Promise<SecurityJobRow[]>;

export function createSecurityJobLoader(fetchRows: FetchSecurityJobRows) {
  return async function loadSecurityJob(
    operatorId: string,
    jobId: string,
  ): Promise<WorkflowJobReceipt | null> {
    const rows = await fetchRows(operatorId, jobId);
    if (rows.length === 0) return null;
    if (rows.length !== 1) {
      throw new Error("security onboarding job identity is ambiguous");
    }
    const row = rows[0];
    const receipt = parseWorkflowJobReceipt({
      contract_version: "workflow_job_receipt.v1",
      job_id: row.id,
      operator_id: row.operator_id,
      job_type: row.job_type,
      state: row.job_state,
      idempotency_key: row.idempotency_key,
      ticker: row.ticker,
      security_id: row.security_id,
      blocking_reasons: [],
      error_code: row.error_code,
      created_at: row.created_at,
      updated_at: row.updated_at,
    });
    if (receipt.operator_id !== operatorId || receipt.job_id !== jobId) {
      throw new Error("security onboarding job is outside requested owner scope");
    }
    return receipt;
  };
}
