import {
  createResearchRunCommandLoader,
  type ResearchRunCommandRow,
} from "./research-run-command-loader";
import { createClient } from "./supabase/server";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const loadFromRows = createResearchRunCommandLoader(
  async (operatorId, commandId) => {
    const supabase = await createClient();
    const { data, error } = await supabase
      .from("iros_research_run_commands")
      .select(
        "contract_version,id,operator_id,security_id,question_type_version,workflow_config_version,as_of_cutoff,operator_focus_normalized,idempotency_key,capture_id,capture_revision,capture_content_hash,command_state,blocking_reason_codes,error_code,research_run_id,created_at,updated_at,started_at,finished_at",
      )
      .eq("operator_id", operatorId)
      .eq("id", commandId)
      .limit(2);
    if (error) {
      throw new Error("Research Run command status failed");
    }
    return (data ?? []) as ResearchRunCommandRow[];
  },
);

export async function loadResearchRunCommand(
  operatorId: string,
  commandId: string,
) {
  if (!UUID_PATTERN.test(operatorId) || !UUID_PATTERN.test(commandId)) {
    return null;
  }
  return loadFromRows(operatorId, commandId);
}
