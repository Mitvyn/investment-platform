import {
  createResearchRunHistoryLoader,
  type ResearchRunReadinessViewRow,
} from "./research-run-history-loader";
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

async function fetchResearchRunRows(
  operatorId: string,
  securityId: string,
): Promise<unknown[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_research_run_eligibility")
    .select(RESEARCH_RUN_FIELDS)
    .eq("operator_id", operatorId)
    .eq("security_id", securityId)
    .order("created_at", { ascending: false })
    .order("research_run_id", { ascending: false })
    .order("check_ordinal", { ascending: true });
  if (error) {
    throw new Error(`Research Run history API failed: ${error.message}`);
  }
  return data ?? [];
}

async function fetchReadinessRows(
  operatorId: string,
  researchRunIds: string[],
): Promise<ResearchRunReadinessViewRow[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_research_run_readiness")
    .select(
      "operator_id,research_run_id,committee_result_id,committee_memo_id,canonical_readiness",
    )
    .eq("operator_id", operatorId)
    .in("research_run_id", researchRunIds);
  if (error) {
    throw new Error(`Research Run readiness history API failed: ${error.message}`);
  }
  return (data ?? []) as unknown as ResearchRunReadinessViewRow[];
}

export const loadResearchRunHistory = createResearchRunHistoryLoader(
  fetchResearchRunRows,
  fetchReadinessRows,
);
