import {
  mapResearchRunRows,
  type ResearchRun,
} from "@iros/types";

import { createClient } from "./supabase/server";

const RESEARCH_RUN_FIELDS = [
  "operator_id",
  "research_run_id",
  "security_id",
  "security_identity_snapshot",
  "question_type",
  "question_type_version_id",
  "workflow_config_version_id",
  "thesis_contract_id",
  "as_of_cutoff",
  "operator_focus_original",
  "operator_focus_normalized",
  "status",
  "idempotency_key",
  "created_at",
  "eligibility_policy_version",
  "eligible",
  "evaluated_at",
  "check_ordinal",
  "rule_id",
  "rule_version",
  "passed",
  "evidence_reference",
  "reason_code",
  "explanation",
  "check_evaluated_at",
].join(",");

export async function loadResearchRun(
  operatorId: string,
  runId: string,
): Promise<ResearchRun | null> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_research_run_eligibility")
    .select(RESEARCH_RUN_FIELDS)
    .eq("operator_id", operatorId)
    .eq("research_run_id", runId)
    .order("check_ordinal", { ascending: true });

  if (error) {
    throw new Error(`Research Run API failed: ${error.message}`);
  }
  if (!data?.length) return null;
  return mapResearchRunRows(data);
}
