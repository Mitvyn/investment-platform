import {
  createModelCostLoader,
  type ModelCostAttemptRow,
  type ModelCostBudgetRow,
  type ModelCostReservationRow,
} from "./model-cost-loader.ts";

async function fetchBudgetRows(
  operatorId: string,
  researchRunId: string,
): Promise<ModelCostBudgetRow[]> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_model_cost_budgets")
    .select(
      "operator_id,research_run_id,budget_id,budget_policy_version,currency,budget_state,hard_cost_limit_usd,hard_token_limit,current_reserved_cost_usd,current_reconciled_cost_usd,current_reserved_tokens,current_reconciled_tokens,remaining_cost_usd,remaining_tokens,created_at",
    )
    .eq("operator_id", operatorId)
    .eq("research_run_id", researchRunId)
    .order("created_at", { ascending: true });
  if (error) throw new Error(`Model cost budget API failed: ${error.message}`);
  return (data ?? []) as ModelCostBudgetRow[];
}

async function fetchReservationRows(
  operatorId: string,
  researchRunId: string,
): Promise<ModelCostReservationRow[]> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_model_cost_reservations")
    .select(
      "operator_id,research_run_id,execution_kind,execution_id,attempt_number,reservation_id,budget_id,budget_policy_version,currency,price_card_version,reservation_state,reserved_cost_usd,reconciled_cost_usd,reserved_tokens,reconciled_tokens,reserved_at,reconciled_at",
    )
    .eq("operator_id", operatorId)
    .eq("research_run_id", researchRunId)
    .order("reserved_at", { ascending: true });
  if (error) {
    throw new Error(`Model cost reservation API failed: ${error.message}`);
  }
  return (data ?? []) as ModelCostReservationRow[];
}

async function fetchAttemptRows(
  operatorId: string,
  researchRunId: string,
): Promise<ModelCostAttemptRow[]> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_model_cost_attempts")
    .select(
      "operator_id,research_run_id,security_id,execution_kind,execution_role,execution_id,attempt_id,attempt_number,execution_state,attempt_result,provider,model,model_config_id,prompt_version,price_card_version,currency,price_card_state,validation_status,schema_valid,citations_valid,validation_error_count,retry_recorded,input_tokens,cached_input_tokens,cache_write_tokens,uncached_input_tokens,output_tokens,reasoning_tokens,total_tokens,tool_call_count,usage_complete,reserved_cost_usd,reconciled_cost_usd,estimated_cost_usd,billed_cost_usd,reservation_state,budget_id,budget_policy_version,hard_cost_limit_usd,hard_token_limit,current_reserved_cost_usd,current_reconciled_cost_usd,current_reserved_tokens,current_reconciled_tokens,remaining_cost_usd,remaining_tokens,started_at,finished_at,duration_ms",
    )
    .eq("operator_id", operatorId)
    .eq("research_run_id", researchRunId)
    .order("started_at", { ascending: true });
  if (error) throw new Error(`Model cost attempt API failed: ${error.message}`);
  return (data ?? []) as ModelCostAttemptRow[];
}

export const loadModelCosts = createModelCostLoader(
  fetchBudgetRows,
  fetchReservationRows,
  fetchAttemptRows,
);
