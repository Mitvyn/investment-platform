import {
  createOperatorDecisionLoader,
  type CurrentOperatorDecisionViewRow,
  type OperatorDecisionEffectViewRow,
  type OperatorDecisionHistoryViewRow,
} from "./operator-decision-loader.ts";

const HISTORY_FIELDS = [
  "operator_id",
  "security_id",
  "thesis_contract_id",
  "canonical_history",
].join(",");
const CURRENT_FIELDS = [
  "operator_id",
  "security_id",
  "thesis_contract_id",
  "current_operator_decision_id",
  "canonical_current_state",
].join(",");
const EFFECT_FIELDS = [
  "operator_id",
  "security_id",
  "thesis_contract_id",
  "operator_decision_id",
  "thesis_version_id",
  "committee_result_id",
  "readiness_gate_result_id",
  "canonical_decision",
  "canonical_thesis",
  "canonical_readiness",
  "canonical_command",
  "canonical_marker",
].join(",");

async function fetchHistoryRows(
  operatorId: string,
  securityId: string,
  thesisContractId: string,
): Promise<OperatorDecisionHistoryViewRow[]> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_operator_decision_history")
    .select(HISTORY_FIELDS)
    .eq("operator_id", operatorId)
    .eq("security_id", securityId)
    .eq("thesis_contract_id", thesisContractId)
    .limit(2);
  if (error) throw new Error(`Operator Decision History API failed: ${error.message}`);
  return (data ?? []) as unknown as OperatorDecisionHistoryViewRow[];
}

async function fetchCurrentRows(
  operatorId: string,
  securityId: string,
  thesisContractId: string,
): Promise<CurrentOperatorDecisionViewRow[]> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_current_operator_decisions")
    .select(CURRENT_FIELDS)
    .eq("operator_id", operatorId)
    .eq("security_id", securityId)
    .eq("thesis_contract_id", thesisContractId)
    .limit(2);
  if (error) throw new Error(`Current Operator Decision API failed: ${error.message}`);
  return (data ?? []) as unknown as CurrentOperatorDecisionViewRow[];
}

async function fetchEffectRows(
  operatorId: string,
  securityId: string,
  thesisContractId: string,
): Promise<OperatorDecisionEffectViewRow[]> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_operator_decision_effects")
    .select(EFFECT_FIELDS)
    .eq("operator_id", operatorId)
    .eq("security_id", securityId)
    .eq("thesis_contract_id", thesisContractId);
  if (error) throw new Error(`Operator Decision Effects API failed: ${error.message}`);
  return (data ?? []) as unknown as OperatorDecisionEffectViewRow[];
}

export const loadOperatorDecisions = createOperatorDecisionLoader(
  fetchHistoryRows,
  fetchCurrentRows,
  fetchEffectRows,
);
