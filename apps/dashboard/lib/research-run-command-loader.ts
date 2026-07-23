import {
  parseResearchRunCommandReceipt,
  type ResearchRunCommandReceipt,
} from "../../../packages/types/research-run-command.ts";

export type ResearchRunCommandRow = {
  id: unknown;
  operator_id: unknown;
  security_id: unknown;
  question_type_version: unknown;
  workflow_config_version: unknown;
  as_of_cutoff: unknown;
  operator_focus_normalized: unknown;
  idempotency_key: unknown;
  command_state: unknown;
  blocking_reason_codes: unknown;
  error_code: unknown;
  research_run_id: unknown;
  created_at: unknown;
  updated_at: unknown;
  started_at: unknown;
  finished_at: unknown;
};

type FetchResearchRunCommandRows = (
  operatorId: string,
  commandId: string,
) => Promise<ResearchRunCommandRow[]>;

export function createResearchRunCommandLoader(
  fetchRows: FetchResearchRunCommandRows,
) {
  return async function loadResearchRunCommand(
    operatorId: string,
    commandId: string,
  ): Promise<ResearchRunCommandReceipt | null> {
    const rows = await fetchRows(operatorId, commandId);
    if (rows.length === 0) return null;
    if (rows.length !== 1) {
      throw new Error("Research Run command identity is ambiguous");
    }
    const row = rows[0];
    const receipt = parseResearchRunCommandReceipt({
      contract_version: "research_run_command_receipt.v1",
      command_id: row.id,
      operator_id: row.operator_id,
      security_id: row.security_id,
      question_type_version: row.question_type_version,
      workflow_config_version: row.workflow_config_version,
      as_of_cutoff: row.as_of_cutoff,
      operator_focus_normalized: row.operator_focus_normalized,
      idempotency_key: row.idempotency_key,
      state: row.command_state,
      blocking_reason_codes: row.blocking_reason_codes,
      error_code: row.error_code,
      research_run_id: row.research_run_id,
      created_at: row.created_at,
      updated_at: row.updated_at,
      started_at: row.started_at,
      finished_at: row.finished_at,
    });
    if (
      receipt.operator_id !== operatorId ||
      receipt.command_id !== commandId
    ) {
      throw new Error(
        "Research Run command is outside requested owner scope",
      );
    }
    return receipt;
  };
}
