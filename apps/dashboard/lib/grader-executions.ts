import { parseGraderExecution } from "@iros/types";

import {
  createGraderExecutionLoader,
  type GraderExecutionViewRow,
} from "./grader-execution-loader.ts";

async function fetchGraderExecutionRows(
  operatorId: string,
  researchRunId: string,
): Promise<GraderExecutionViewRow[]> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_research_run_grader_executions")
    .select(
      "operator_id,research_run_id,evidence_bundle_id,grader_execution_id,grader_id,grader_version,canonical_execution",
    )
    .eq("operator_id", operatorId)
    .eq("research_run_id", researchRunId)
    .order("grader_id", { ascending: true });

  if (error) {
    throw new Error(`Grader Execution API failed: ${error.message}`);
  }
  return (data ?? []).map((row: { canonical_execution: unknown }) => ({
    canonical_execution: row.canonical_execution,
  }));
}

export const loadGraderExecutions = createGraderExecutionLoader(
  fetchGraderExecutionRows,
  parseGraderExecution,
);
