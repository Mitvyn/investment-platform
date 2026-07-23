import {
  parseCommitteeState,
  type CommitteeValidationContext,
} from "@iros/types";

import {
  createGraderCommitteeLoader,
  type GraderCommitteeViewRow,
} from "./grader-committee-loader.ts";

async function fetchGraderCommitteeRows(
  operatorId: string,
  researchRunId: string,
): Promise<GraderCommitteeViewRow[]> {
  const { createClient } = await import("./supabase/server.ts");
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("iros_v_research_run_committees")
    .select(
      "operator_id,research_run_id,committee_result_id,canonical_committee",
    )
    .eq("operator_id", operatorId)
    .eq("research_run_id", researchRunId)
    .limit(2);

  if (error) {
    throw new Error(`Research Committee API failed: ${error.message}`);
  }
  return (data ?? []).map(
    (row: {
      operator_id: string;
      research_run_id: string;
      canonical_committee: unknown;
    }) => ({
      operator_id: row.operator_id,
      research_run_id: row.research_run_id,
      canonical_committee: row.canonical_committee,
    }),
  );
}

export async function loadGraderCommittee(
  operatorId: string,
  researchRunId: string,
  context: CommitteeValidationContext,
) {
  return createGraderCommitteeLoader(
    fetchGraderCommitteeRows,
    (value) => parseCommitteeState(value, context),
  )(operatorId, researchRunId);
}
